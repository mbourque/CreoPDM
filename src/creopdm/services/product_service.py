"""Product lifecycle: create, list, open, delete. Git init is an implementation detail."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from creopdm.constants import (
    DEFAULT_BRANCH,
    PRODUCT_JSON_NAME,
    PRODUCT_MARKER_DIR,
    ActivityAction,
    CheckoutStatus,
    ProductState,
)
from creopdm.exceptions import (
    DuplicateProductError,
    PathValidationError,
    ProductNotFoundError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.product_state import ensure_product_deletable, parse_product_state
from creopdm.utils.vault_folder import normalize_uuid_folder, validate_vault_folder
from creopdm.logging_setup import get_logger
from creopdm.models.activity import Activity
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.remote import Remote
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.files import remove_tree
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.classify import matches_cad_models, matches_document
from creopdm.utils.native_dialog import default_product_location_start

logger = get_logger("products")


class ProductService:
    def __init__(
        self,
        git: GitService,
        locks: ProductLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
        workspaces: WorkspaceService,
    ) -> None:
        self._git = git
        self._locks = locks
        self._activities = activities
        self._users = users
        self._workspaces = workspaces

    def list_products(
        self,
        session: Session,
        include_inactive: bool = False,
        *,
        include_archived: bool = False,
    ) -> list[Product]:
        stmt = select(Product).order_by(Product.name.asc())
        if not include_inactive:
            stmt = stmt.where(Product.active.is_(True))
        if not include_archived:
            # ARCHIVED is hidden from normal Files / API lists (admin passes include_archived).
            stmt = stmt.where(Product.state != ProductState.ARCHIVED.value)
        return list(session.scalars(stmt))

    def _load_product(self, session: Session, product_uuid: str) -> Product:
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None or not product.active:
            raise ProductNotFoundError(
                "Product not found.",
                details={"uuid": product_uuid},
            )
        return product

    def load_product_for_delete(self, session: Session, product_uuid: str) -> Product:
        """Load any product row for unregister — including inactive / archived."""
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None:
            raise ProductNotFoundError(
                "Product not found.",
                details={"uuid": product_uuid},
            )
        return product

    def get_product(self, session: Session, product_uuid: str) -> Product:
        product = self._load_product(session, product_uuid)
        self._workspaces.ensure_vault(product)
        return product

    def _require_unique_name(
        self,
        session: Session,
        name: str,
        *,
        exclude_uuid: str | None = None,
    ) -> None:
        """Reject duplicate names across all products (including inactive / archived)."""
        wanted = name.strip().casefold()
        for existing in session.scalars(select(Product)):
            if exclude_uuid and existing.uuid == exclude_uuid:
                continue
            if existing.name.strip().casefold() == wanted:
                raise DuplicateProductError(
                    f'A product named "{existing.name}" already exists.',
                    details={"name": existing.name, "uuid": existing.uuid},
                )

    def _require_unique_vault_folder(
        self,
        session: Session,
        vault_folder: str,
        *,
        exclude_uuid: str | None = None,
    ) -> None:
        wanted = vault_folder.casefold()
        stmt = select(Product).where(Product.active.is_(True))
        for existing in session.scalars(stmt):
            if exclude_uuid and existing.uuid == exclude_uuid:
                continue
            existing_folder = (existing.vault_folder or existing.uuid).casefold()
            if existing_folder == wanted:
                raise DuplicateProductError(
                    f'A product already uses vault/workspace name "{existing.vault_folder or existing.uuid}".',
                    details={"vault_folder": existing.vault_folder or existing.uuid},
                )
            if existing.uuid.casefold() == wanted:
                raise DuplicateProductError(
                    f'Vault/workspace name "{vault_folder}" matches another product id.',
                    details={"vault_folder": vault_folder},
                )

    def create_product(
        self,
        session: Session,
        name: str,
        number: str | None = None,
        description: str | None = None,
        vault_folder: str | None = None,
        *,
        state: str | None = None,
        read_only: bool = False,
    ) -> Product:
        if not name.strip():
            raise PathValidationError("A product name is required.")
        self._require_unique_name(session, name)

        requested = (vault_folder or "").strip()
        if requested:
            folder = validate_vault_folder(requested)
            as_uuid = normalize_uuid_folder(folder)
            product_uuid = as_uuid or str(uuid.uuid4())
            if as_uuid:
                folder = as_uuid
        else:
            product_uuid = str(uuid.uuid4())
            folder = product_uuid

        self._require_unique_vault_folder(session, folder)

        vault_root = self._workspaces._config.workspace_root()
        vault_path = vault_root / folder
        if vault_path.exists() and any(vault_path.iterdir()):
            raise DuplicateProductError(
                f'Vault folder "{folder}" already exists on disk.',
                details={"vault_folder": folder, "path": str(vault_path)},
            )

        user = self._users.get_current_user()
        now = datetime.now(timezone.utc)
        initial_state = parse_product_state(state) if state is not None else ProductState.IN_WORK.value

        if not self._git.is_available():
            raise RepositoryError("Git is required to create a product but was not found on PATH.")

        with self._locks.acquire(product_uuid):
            vault = self._workspaces.init_vault(folder, product_uuid, name.strip(), user)

        product = Product(
            uuid=product_uuid,
            name=name.strip(),
            number=(number or "").strip() or None,
            description=(description or "").strip() or None,
            vault_folder=folder,
            repository_path="",
            default_branch=DEFAULT_BRANCH,
            state=initial_state,
            read_only=bool(read_only),
            created_at=now,
            updated_at=now,
            active=True,
        )
        session.add(product)
        session.flush()
        self._activities.record(
            session,
            ActivityAction.PRODUCT_CREATED,
            user,
            product_id=product.id,
            details={"workspace": str(vault), "name": product.name, "vault_folder": folder},
        )
        logger.info("Created product %s in workspace %s", product.uuid, vault)
        session.commit()
        return product

    def update_product(
        self,
        session: Session,
        product_uuid: str,
        name: str,
        number: str | None = None,
        description: str | None = None,
        *,
        state: str | None = None,
        read_only: bool | None = None,
    ) -> Product:
        """Update name/number/description/state/read_only. Never changes vault_folder."""
        product = self.get_product(session, product_uuid)
        new_name = name.strip()
        if not new_name:
            raise ValidationAppError("A product name is required.")
        self._require_unique_name(session, new_name, exclude_uuid=product.uuid)
        new_number = (number or "").strip() or None
        new_description = (description or "").strip() or None
        new_state = parse_product_state(state) if state is not None else None
        user = self._users.get_current_user()
        old_number = (product.number or "").strip() or None
        old_description = (product.description or "").strip() or None
        old_state = product.state
        old_read_only = bool(product.read_only)
        identity_changed = (
            new_name != product.name
            or new_number != old_number
            or new_description != old_description
        )
        old_name = product.name

        # State / read-only live in the DB only — do not touch the vault Git repo.
        # (A dirty vault with CAD files used to make "rename" commit fail on Save.)
        if identity_changed:
            vault = self._workspaces.ensure_vault(product)
            marker_rel = f"{PRODUCT_MARKER_DIR}/{PRODUCT_JSON_NAME}"
            with self._locks.acquire(product.uuid):
                captured = None
                try:
                    captured = self._git.get_head(vault)
                except Exception:
                    captured = None
                self._workspaces.write_product_marker(product, new_name, new_number, new_description)
                try:
                    self._git.stage_files(vault, [marker_rel])
                    # Only commit when the marker is staged — not when other vault
                    # files are dirty (checkout leftovers, untracked saves, …).
                    staged = self._git.status(vault).staged
                    if staged:
                        self._git.commit(vault, f"Rename product to {new_name}", user)
                except Exception as exc:
                    if captured:
                        try:
                            self._git.reset_to(vault, captured)
                        except Exception:
                            logger.exception("Could not restore vault after failed product rename")
                    raise RepositoryError(
                        "Could not record the product rename in the vault.",
                        details={"name": new_name, "cause": str(exc)},
                    ) from exc
                try:
                    product.name = new_name
                    product.number = new_number
                    product.description = new_description
                    if new_state is not None:
                        product.state = new_state
                    if read_only is not None:
                        product.read_only = bool(read_only)
                    product.updated_at = datetime.now(timezone.utc)
                    session.flush()
                    self._activities.record(
                        session,
                        ActivityAction.PRODUCT_UPDATED,
                        user,
                        product_id=product.id,
                        details={
                            "old_name": old_name,
                            "name": new_name,
                            "old_state": old_state,
                            "new_state": product.state,
                            "old_read_only": old_read_only,
                            "read_only": bool(product.read_only),
                        },
                    )
                except Exception as exc:
                    if captured:
                        try:
                            self._git.reset_to(vault, captured)
                        except Exception:
                            logger.exception("Could not restore vault after failed product metadata save")
                    raise RepositoryError(
                        "The vault was updated but product metadata could not be saved. "
                        "The repository was restored.",
                        details={"name": new_name},
                    ) from exc
        else:
            if new_state is not None:
                product.state = new_state
            if read_only is not None:
                product.read_only = bool(read_only)
            product.updated_at = datetime.now(timezone.utc)
            session.flush()
            self._activities.record(
                session,
                ActivityAction.PRODUCT_UPDATED,
                user,
                product_id=product.id,
                details={
                    "old_name": old_name,
                    "name": new_name,
                    "old_state": old_state,
                    "new_state": product.state,
                    "old_read_only": old_read_only,
                    "read_only": bool(product.read_only),
                },
            )

        logger.info("Updated product %s (%s)", product.uuid, new_name)
        session.commit()
        return product

    def delete_product(self, session: Session, product_uuid: str) -> None:
        """Unregister the product and delete its CreoPDM vault folder.

        Original CAD folders the user imported from are never touched. The vault
        under the configured vaults root is removed so deletes do not leave
        orphan Git trees on disk. Works for inactive / Archived products too.
        """
        product = self.load_product_for_delete(session, product_uuid)
        ensure_product_deletable(product, action="delete this product")
        workspace = self._workspaces.vault_for(product)
        leftover = self._workspaces.leftover_source(product)
        with self._locks.acquire(product.uuid):
            if leftover is not None:
                self._workspaces.strip_location_git(leftover)
            if workspace.exists() and not remove_tree(workspace):
                raise RepositoryError(
                    "Could not delete the vault folder. Close File Explorer or other "
                    "programs using that folder, then try again.",
                    details={"path": str(workspace)},
                )
            self._delete_product_records(session, product)
        logger.info("Deleted product %s (vault removed)", product.uuid)

    def forget_product(
        self,
        session: Session,
        product_uuid: str,
        confirm_name: str,
        workspace_path: Path | None = None,
    ) -> dict[str, str]:
        """Unregister the product and delete the workspace Git vault."""
        product = self.load_product_for_delete(session, product_uuid)
        ensure_product_deletable(product, action="delete this product")
        expected = product.name.strip()
        if confirm_name.strip() != expected:
            raise ValidationAppError(
                "Type the product name exactly to delete it.",
                details={"name": expected},
            )
        leftover = self._workspaces.leftover_source(product)
        name = product.name
        vault = workspace_path if workspace_path is not None else self._workspaces.vault_for(product)
        warnings: list[str] = []
        # Timed wait: a cancelled Add can still hold the lock briefly; do not hang forever.
        with self._locks.acquire(product.uuid, timeout=45.0):
            if leftover is not None:
                self._workspaces.strip_location_git(leftover)
                if (leftover / ".git").exists():
                    warnings.append(
                        "Git metadata is still present because a program has the old product folder open."
                    )
            if vault.exists() and not remove_tree(vault):
                raise RepositoryError(
                    "Could not delete the vault folder. Close File Explorer or other "
                    "programs using that folder, then try again.",
                    details={"path": str(vault)},
                )
            self._delete_product_records(session, product)
        logger.info("Deleted product %s", product_uuid)
        session.commit()
        return {
            "uuid": product_uuid,
            "name": name,
            "repository_path": str(leftover) if leftover is not None else "",
            "warning": " ".join(warnings) if warnings else "",
        }

    def _delete_product_records(self, session: Session, product: Product) -> None:
        objects = list(
            session.scalars(select(EngineeringObject).where(EngineeringObject.product_id == product.id))
        )
        object_ids = [item.id for item in objects]
        if object_ids:
            session.execute(
                update(EngineeringObject)
                .where(EngineeringObject.id.in_(object_ids))
                .values(current_version_id=None)
            )
            session.flush()
            session.execute(delete(Parameter).where(Parameter.object_id.in_(object_ids)))
            session.execute(delete(Checkout).where(Checkout.object_id.in_(object_ids)))
            session.execute(
                delete(Dependency).where(
                    or_(
                        Dependency.parent_object_id.in_(object_ids),
                        Dependency.child_object_id.in_(object_ids),
                    )
                )
            )
            session.execute(delete(Activity).where(Activity.object_id.in_(object_ids)))
            session.execute(delete(ObjectVersion).where(ObjectVersion.object_id.in_(object_ids)))
            session.execute(delete(EngineeringObject).where(EngineeringObject.id.in_(object_ids)))
        session.execute(delete(Dependency).where(Dependency.product_id == product.id))
        session.execute(delete(Activity).where(Activity.product_id == product.id))
        session.execute(delete(Remote).where(Remote.product_id == product.id))
        session.delete(product)
        session.flush()

    def preferred_import_directory(self, product: Product) -> Path:
        """Folder the Add Files dialog should start in."""
        leftover = self._workspaces.leftover_source(product)
        if leftover is not None and leftover.is_dir():
            return leftover
        return default_product_location_start()

    def product_status(
        self,
        session: Session,
        product_uuid: str,
        objects: list | None = None,
        product: Product | None = None,
    ) -> dict[str, int | str]:
        product = product or self.get_product(session, product_uuid)
        if objects is None:
            objects = list(
                session.scalars(
                    select(EngineeringObject).where(EngineeringObject.product_id == product.id)
                )
            )
        user = self._users.get_current_user()
        active = list(
            session.scalars(
                select(Checkout)
                .join(EngineeringObject, Checkout.object_id == EngineeringObject.id)
                .where(
                    EngineeringObject.product_id == product.id,
                    Checkout.status == CheckoutStatus.ACTIVE.value,
                )
            )
        )
        mine = sum(1 for row in active if row.user_name == user.user_name)
        models = self._workspaces._config.cad_models_extensions()
        documents = self._workspaces._config.document_extensions()
        counts: dict[str, int | str] = {
            "files": len(objects),
            "cad_models": sum(
                1 for obj in objects if matches_cad_models(obj.filename, models, obj.extension)
            ),
            "creo_parts": sum(1 for obj in objects if obj.object_type == "CREO_PART"),
            "assemblies": sum(1 for obj in objects if obj.object_type == "CREO_ASSEMBLY"),
            "drawings": sum(1 for obj in objects if obj.object_type == "CREO_DRAWING"),
            "documents": sum(
                1 for obj in objects if matches_document(obj.filename, documents, obj.extension)
            ),
            "other": sum(
                1
                for obj in objects
                if not matches_cad_models(obj.filename, models, obj.extension)
            ),
            "checked_out": len(active),
            "checked_out_by_me": mine,
            "checked_out_by_others": len(active) - mine,
            "modified_locally": 0,
            "out_of_date": 0,
            "untracked": 0,
        }
        return counts
