"""Product lifecycle: create, list, open, delete. Git init is an implementation detail."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import (
    DEFAULT_BRANCH,
    DEFAULT_REVISION,
    INITIAL_ITERATION,
    PRODUCT_JSON_NAME,
    PRODUCT_MARKER_DIR,
    ActivityAction,
    CheckoutStatus,
    LifecycleState,
    ProductState,
)
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import (
    DuplicateProductError,
    PathValidationError,
    ProductNotFoundError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.lifecycle_policy import get_lifecycle_policy
from creopdm.product_state import (
    ensure_product_deletable,
    parse_product_state,
)
from creopdm.utils.vault_folder import normalize_uuid_folder, validate_vault_folder
from creopdm.logging_setup import get_logger
from creopdm.models.ai_snapshot import ObjectVersionSnapshot
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.remote import Remote
from creopdm.models.revise_operation import ReviseOperation
from creopdm.services.comment_service import purge_product_comments
from creopdm.services.baseline_guard import count_product_baselines, delete_product_baselines
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.git_service import GitService
from creopdm.services.object_service import ObjectService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.files import remove_tree
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.classify import matches_cad_models, matches_document
from creopdm.utils.native_dialog import default_product_location_start

logger = get_logger("products")

# Promote refuses these while any file is checked out.
_CHECKOUT_GUARDED_STATES = frozenset(
    {
        ProductState.IN_REVIEW.value,
        ProductState.APPROVED.value,
        ProductState.RELEASED.value,
    }
)


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
        # Set by app.py: the baseline service that records a release (R1, R2, ...).
        self.release_baselines = None

    def list_products(
        self,
        session: Session,
        include_inactive: bool = False,
        *,
        include_archived: bool = False,
        include_templates: bool = False,
        only_templates: bool = False,
    ) -> list[Product]:
        """Regular products. Templates are listed only when asked for (they are not products to work in)."""
        stmt = select(Product).order_by(Product.name.asc())
        if only_templates:
            stmt = stmt.where(Product.is_template.is_(True))
        elif not include_templates:
            stmt = stmt.where(Product.is_template.is_(False))
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
        copied_from: Product | None = None,
        copied_file_count: int | None = None,
        is_template: bool = False,
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
            created_at=now,
            updated_at=now,
            active=True,
            is_template=is_template,
        )
        session.add(product)
        session.flush()
        details: dict[str, str | int] = {"name": product.name, "vault_folder": folder}
        action = ActivityAction.TEMPLATE_CREATED if is_template else ActivityAction.PRODUCT_CREATED
        if copied_from is not None:
            action = ActivityAction.PRODUCT_COPIED
            details["source_name"] = copied_from.name
            details["source_uuid"] = copied_from.uuid
            if copied_from.is_template:
                details["template"] = copied_from.name
            if copied_file_count is not None:
                details["file_count"] = copied_file_count
        self._activities.record(
            session,
            action,
            user,
            product_id=product.id,
            details=details,
        )
        if copied_from is not None:
            logger.info(
                "Copied product %s to %s in workspace %s",
                copied_from.uuid,
                product.uuid,
                vault,
            )
        else:
            logger.info("Created product %s in workspace %s", product.uuid, vault)
        session.commit()
        return product

    def copy_source_summary(self, session: Session, source_uuid: str) -> dict[str, str | int]:
        """Name, number, description, and the Add-style default comment for the copy form."""
        source = self.load_product_for_delete(session, source_uuid)
        jobs = self._vault_content_jobs(self._workspaces.vault_for(source))
        single = jobs[0][1] if len(jobs) == 1 else None
        from creopdm.utils.import_comments import resolve_add_commit_message

        comment = resolve_add_commit_message(
            None,
            planned_count=len(jobs),
            single_filename=single,
            first_check_in=True,
        )
        return {
            "name": source.name,
            "number": source.number or "",
            "description": source.description or "",
            "comment": comment,
            "file_count": len(jobs),
            "uuid": source.uuid,
        }

    def copy_product(
        self,
        session: Session,
        objects: ObjectService,
        source_uuid: str,
        name: str,
        number: str | None = None,
        description: str | None = None,
        comment: str | None = None,
        vault_folder: str | None = None,
    ) -> Product:
        """Create a new product and Add the source vault's current files into it.

        New id, new vault, one Add commit. Files are A.1 / In Work and not
        checked out. Current metadata and Where Used are copied onto those
        new rows. Revision history, checkouts, watches, and membership are not.
        Thumbnails stay keyed by file hash, so the original product keeps them.
        """
        source = self.load_product_for_delete(session, source_uuid)
        source_vault = self._workspaces.vault_for(source)
        if not source_vault.is_dir():
            raise PathValidationError(
                "This product has no vault folder to copy.",
                details={"uuid": source.uuid},
            )
        with self._locks.acquire(source.uuid):
            jobs = self._vault_content_jobs(source_vault)
            from creopdm.utils.import_comments import resolve_add_commit_message

            single = jobs[0][1] if len(jobs) == 1 else None
            message = resolve_add_commit_message(
                comment,
                planned_count=len(jobs),
                single_filename=single,
                first_check_in=True,
            )
            # Always a new In Work product — do not carry the source lifecycle state.
            created = self.create_product(
                session,
                name,
                number,
                description,
                vault_folder=(vault_folder or "").strip() or None,
                state=ProductState.IN_WORK.value,
                copied_from=source,
                copied_file_count=len(jobs),
            )
            empty_folders = self._empty_vault_folders(source_vault, jobs)
            if not jobs and not empty_folders:
                return created
            try:
                if jobs:
                    outcomes = objects.import_files(session, created, jobs, message)
                    failed = [item for item in outcomes if item.error is not None]
                    if failed:
                        first = failed[0].error
                        detail = first.message if first is not None else "A file could not be copied."
                        raise ValidationAppError(
                            f"Could not copy {failed[0].filename}: {detail}",
                            details={"filename": failed[0].filename},
                        )
                    self._copy_current_metadata(session, source, created)
                # Folders with no files in them (kept in Git by a .gitkeep) are part of the structure too.
                user = self._users.get_current_user()
                for folder in empty_folders:
                    parent, _sep, leaf = folder.rpartition("/")
                    self._workspaces.create_folder(
                        created, name=leaf, parent_folder=parent, user=user, comment=f"Create folder {folder}"
                    )
                session.commit()
            except Exception:
                session.rollback()
                self._discard_copied_product(session, created.uuid)
                raise
        logger.info(
            "Copied product %s to %s (%s files)",
            source.uuid,
            created.uuid,
            len(jobs),
        )
        return created

    def _empty_vault_folders(self, vault: Path, jobs: list[tuple[Path, str, str]]) -> list[str]:
        """Deepest folders of the vault that hold no file (only a .gitkeep, or nothing), as vault paths."""
        if not vault.is_dir():
            return []
        used: set[str] = set()
        for _path, _name, relative in jobs:
            parts = relative.split("/")[:-1]
            for index in range(1, len(parts) + 1):
                used.add("/".join(parts[:index]))
        skip_dirs = {".git", PRODUCT_MARKER_DIR}
        found: list[str] = []
        for dirpath, dirnames, _filenames in os.walk(vault):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            for name in list(dirnames):
                relative = (Path(dirpath) / name).relative_to(vault).as_posix()
                if relative in used or any(part.startswith(".") for part in relative.split("/")):
                    continue
                found.append(relative)
        # Keep only the deepest empty folders: creating one makes its parents.
        deepest = [item for item in found if not any(other.startswith(item + "/") for other in found)]
        return sorted(deepest)

    def _vault_content_jobs(self, vault: Path) -> list[tuple[Path, str, str]]:
        """Current vault files an Add would store. Skips Git, the product marker, and ignored names."""
        if not vault.is_dir():
            return []
        ignore = self._workspaces._config.ignore_patterns()
        skip_dirs = {".git", PRODUCT_MARKER_DIR}
        jobs: list[tuple[Path, str, str]] = []
        for dirpath, dirnames, filenames in os.walk(vault):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            for name in filenames:
                if name in {".gitignore", ".gitkeep"}:
                    continue  # .gitkeep only keeps an empty folder in Git; the folder is copied on its own
                if CreoFileManager.is_ignored(name, ignore):
                    continue
                path = Path(dirpath) / name
                if not path.is_file():
                    continue
                relative = path.relative_to(vault).as_posix()
                jobs.append((path, name, relative))
        jobs.sort(key=lambda item: item[2])
        return jobs

    def _copy_current_metadata(self, session: Session, source: Product, dest: Product) -> None:
        """Copy the source tip's collected metadata and Where Used onto the new A.1 rows.

        Does not copy older versions, checkouts, or watches. The tip's AI snapshot is copied.
        """
        purgeable = self._workspaces._config.purgeable_cad_extensions()
        source_objects = session.scalars(
            select(EngineeringObject)
            .where(EngineeringObject.product_id == source.id)
            .options(joinedload(EngineeringObject.current_version))
        ).unique()
        by_logical: dict[str, EngineeringObject] = {}
        for obj in source_objects:
            by_logical[CreoFileManager.logical_repo_path(obj.relative_path, purgeable)] = obj

        dest_objects = list(
            session.scalars(
                select(EngineeringObject)
                .where(EngineeringObject.product_id == dest.id)
                .options(joinedload(EngineeringObject.current_version))
            ).unique()
        )
        id_map: dict[int, EngineeringObject] = {}
        json_fields = (
            "identity_json",
            "materials_json",
            "bom_json",
            "units_json",
            "mass_json",
            "family_table_json",
            "features_json",
        )
        for dest_obj in dest_objects:
            # import_files already stored A.1 / In Work. Keep that even if the source was released.
            dest_obj.revision = DEFAULT_REVISION
            dest_obj.iteration = INITIAL_ITERATION
            dest_obj.lifecycle_state = LifecycleState.IN_WORK.value
            key = CreoFileManager.logical_repo_path(dest_obj.relative_path, purgeable)
            src = by_logical.get(key)
            if src is None:
                continue
            id_map[src.id] = dest_obj
            src_version = src.current_version
            dest_version = dest_obj.current_version
            if src_version is None or dest_version is None:
                continue
            dest_version.revision = DEFAULT_REVISION
            dest_version.iteration = INITIAL_ITERATION
            for field in json_fields:
                setattr(dest_version, field, getattr(src_version, field))
            if src_version.creo_release:
                dest_version.creo_release = src_version.creo_release
            # The source tip's AI snapshot is the baseline Check In's Ask AI compares against; without it a
            # copied product's A.1 would "have no snapshot yet".
            snap = session.scalar(
                select(ObjectVersionSnapshot).where(ObjectVersionSnapshot.version_id == src_version.id)
            )
            if snap is not None:
                session.add(
                    ObjectVersionSnapshot(
                        uuid=str(uuid.uuid4()),
                        object_id=dest_obj.id,
                        version_id=dest_version.id,
                        schema_version=snap.schema_version,
                        content_hash=dest_version.content_hash or snap.content_hash,
                        capture_status=snap.capture_status,
                        capture_errors=snap.capture_errors,
                        snapshot_json=snap.snapshot_json,
                    )
                )
            params = session.scalars(
                select(Parameter).where(
                    Parameter.object_id == src.id,
                    or_(
                        Parameter.version_id == src_version.id,
                        Parameter.version_id.is_(None),
                    ),
                )
            )
            for param in params:
                session.add(
                    Parameter(
                        object_id=dest_obj.id,
                        version_id=dest_version.id,
                        name=param.name,
                        value=param.value,
                        data_type=param.data_type,
                        units=param.units,
                        description=param.description,
                        is_designated=param.is_designated,
                    )
                )
        edges = session.scalars(select(Dependency).where(Dependency.product_id == source.id))
        for edge in edges:
            parent = id_map.get(edge.parent_object_id)
            child = id_map.get(edge.child_object_id)
            if parent is None or child is None:
                continue
            session.add(
                Dependency(
                    product_id=dest.id,
                    parent_object_id=parent.id,
                    child_object_id=child.id,
                    dependency_type=edge.dependency_type,
                    quantity=edge.quantity,
                )
            )
        session.flush()

    def _discard_copied_product(self, session: Session, product_uuid: str) -> None:
        """Remove a product left behind when copy fails after create."""
        try:
            self.delete_product(session, product_uuid)
        except Exception:
            logger.exception("Could not remove incomplete product copy %s", product_uuid)

    def update_product(
        self,
        session: Session,
        product_uuid: str,
        name: str,
        number: str | None = None,
        description: str | None = None,
        *,
        state: str | None = None,
        reopen_released_files: bool = False,
        create_release_baseline: bool = False,
        create_release_tag: bool = False,
    ) -> Product:
        """Update name/number/description/state. Never changes vault_folder.

        ``reopen_released_files`` (Promote Products, any state -> In Work / Pre-Work) also sets the
        product's Released files back to In Work, i.e. undoes a release. Without it they stay
        Released and change only through Revise.
        """
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
        identity_changed = (
            new_name != product.name
            or new_number != old_number
            or new_description != old_description
        )
        old_name = product.name
        state_changed = new_state is not None and new_state != old_state
        releasing = state_changed and new_state == ProductState.RELEASED.value
        release = None  # set below when this promotion records a release (R1, R2, ...)
        reopening = bool(
            reopen_released_files
            and state_changed
            and new_state in {ProductState.IN_WORK.value, ProductState.PRE_WORK.value}
        )
        if state_changed and new_state in _CHECKOUT_GUARDED_STATES:
            # In Review / Approved / Released block Check Out, and Undo/Force Undo follow the same
            # matrix column, so an open checkout would be stranded. Do not pull it out from under
            # someone either: refuse and say who holds what.
            self._require_no_active_checkouts(session, product, new_state)
        # Lifecycle state on Promote Products is not matrix-gated (no Change Lifecycle
        # State column) — admins with products.edit can leave Locked / any state.

        # State lives in the DB only — do not touch the vault Git repo.
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
                            "old_number": old_number,
                            "number": new_number,
                            "old_description": old_description,
                            "description": new_description,
                        },
                    )
                    if state_changed:
                        released = self._release_objects(session, product) if releasing else 0
                        reopened = self._reopen_objects(session, product) if reopening else 0
                        release = (
                            self._record_release(session, product, user, create_release_tag)
                            if releasing and create_release_baseline
                            else None
                        )
                        self._activities.record(
                            session,
                            ActivityAction.STATE_CHANGED,
                            user,
                            product_id=product.id,
                            details={
                                "old_state": old_state,
                                "new_state": product.state,
                                **({"objects_released": released} if releasing else {}),
                                **({"objects_reopened": reopened} if reopening else {}),
                                **self._release_details(release),
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
        elif state_changed:
            if new_state is not None:
                product.state = new_state
            product.updated_at = datetime.now(timezone.utc)
            session.flush()
            released = self._release_objects(session, product) if releasing else 0
            reopened = self._reopen_objects(session, product) if reopening else 0
            release = (
                self._record_release(session, product, user, create_release_tag)
                if releasing and create_release_baseline
                else None
            )
            self._activities.record(
                session,
                ActivityAction.STATE_CHANGED,
                user,
                product_id=product.id,
                details={
                    "old_state": old_state,
                    "new_state": product.state,
                    **({"objects_released": released} if releasing else {}),
                    **({"objects_reopened": reopened} if reopening else {}),
                    **self._release_details(release),
                },
            )

        logger.info("Updated product %s (%s)", product.uuid, new_name)
        session.commit()
        if release is not None and create_release_tag and self.release_baselines is not None:
            # After the commit: the release and its baseline are complete whatever happens to the
            # tag (a failed tag is recorded on the baseline and can be retried).
            self.release_baselines.apply_release_tag(session, product, release)
        return product

    def _record_release(
        self, session: Session, product: Product, user, tag: bool = False
    ) -> object | None:
        """Release R<n> with its strict Release baseline, in the promotion's own transaction.

        The files are already Released here, so the baseline captures them as released. Any
        refusal propagates and the whole promotion is rolled back.
        """
        if self.release_baselines is None:
            return None
        # Releasing the files was a bulk UPDATE: reload them so the baseline sees "Released".
        session.flush()
        session.expire_all()
        return self.release_baselines.create_release(session, product, user.user_name, tag=tag)

    @staticmethod
    def _release_details(release) -> dict:
        if release is None:
            return {}
        return {"release": release.label, "release_baseline_id": release.baseline_id}

    def _require_no_active_checkouts(
        self, session: Session, product: Product, new_state: str
    ) -> None:
        """Refuse to move a product into In Review / Approved / Released while files are checked out."""
        rows = session.execute(
            select(EngineeringObject.filename, Checkout.user_name)
            .join(Checkout, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.product_id == product.id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
            .order_by(EngineeringObject.filename.asc())
        ).all()
        if not rows:
            return
        shown = "; ".join(f"{name} ({owner})" for name, owner in rows[:5])
        more = f" and {len(rows) - 5} more" if len(rows) > 5 else ""
        label = get_lifecycle_policy().label(new_state)
        raise ValidationAppError(
            f"Cannot move {product.name} to {label}: {len(rows)} file(s) are checked out — "
            f"{shown}{more}. Check them in or undo the checkout first.",
            details={
                "product": product.uuid,
                "checked_out": len(rows),
                "state": new_state,
            },
        )

    def _release_objects(self, session: Session, product: Product) -> int:
        """Releasing a product releases its in-work files (obsolete files stay obsolete).
        Files that are checked out stay In Work.

        Moving the product to an editable state later does not flip them back: a released
        file only becomes editable again through Revise.
        """
        # Files somebody has checked out stay In Work: releasing must not strand their checkout.
        checked_out = select(Checkout.object_id).where(
            Checkout.status == CheckoutStatus.ACTIVE.value
        )
        in_work = select(EngineeringObject.current_version_id).where(
            EngineeringObject.product_id == product.id,
            EngineeringObject.lifecycle_state == LifecycleState.IN_WORK.value,
            EngineeringObject.current_version_id.is_not(None),
            EngineeringObject.id.not_in(checked_out),
        )
        # The released tip is the Released version (A.3 stays RELEASED after Revise).
        session.execute(
            update(ObjectVersion)
            .where(ObjectVersion.id.in_(in_work))
            .values(lifecycle_state=LifecycleState.RELEASED.value)
        )
        result = session.execute(
            update(EngineeringObject)
            .where(
                EngineeringObject.product_id == product.id,
                EngineeringObject.lifecycle_state == LifecycleState.IN_WORK.value,
                EngineeringObject.id.not_in(checked_out),
            )
            .values(lifecycle_state=LifecycleState.RELEASED.value)
        )
        session.flush()
        return int(result.rowcount or 0)

    def _reopen_objects(self, session: Session, product: Product) -> int:
        """Undo a release: the product's Released files go back to In Work.

        Only each file's current version changes; earlier Released revisions (A.x after a Revise)
        keep their own Released state.
        """
        released = select(EngineeringObject.current_version_id).where(
            EngineeringObject.product_id == product.id,
            EngineeringObject.lifecycle_state == LifecycleState.RELEASED.value,
            EngineeringObject.current_version_id.is_not(None),
        )
        session.execute(
            update(ObjectVersion)
            .where(ObjectVersion.id.in_(released))
            .values(lifecycle_state=LifecycleState.IN_WORK.value)
        )
        result = session.execute(
            update(EngineeringObject)
            .where(
                EngineeringObject.product_id == product.id,
                EngineeringObject.lifecycle_state == LifecycleState.RELEASED.value,
            )
            .values(lifecycle_state=LifecycleState.IN_WORK.value)
        )
        session.flush()
        return int(result.rowcount or 0)

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
        workspace_path: Path | None = None,
    ) -> dict[str, str]:
        """Unregister the product and delete the workspace Git vault.

        Callers must verify the signed-in user's password first
        (``require_danger_password``).
        """
        product = self.load_product_for_delete(session, product_uuid)
        ensure_product_deletable(product, action="delete this product")
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
        user = self._users.get_current_user()
        baselines_erased, releases_erased = count_product_baselines(session, product.id)
        # Append-only audit: record delete, then detach FKs — never wipe history.
        self._activities.record(
            session,
            ActivityAction.TEMPLATE_DELETED if product.is_template else ActivityAction.PRODUCT_DELETED,
            user,
            product_id=product.id,
            details={
                "uuid": product.uuid,
                "name": product.name,
                "vault_folder": product.vault_folder or product.uuid,
                **({"baselines_erased": baselines_erased} if baselines_erased else {}),
                **({"releases_erased": releases_erased} if releases_erased else {}),
            },
            product_uuid=product.uuid,
            product_name=product.name,
            comment=f"Deleted {'template' if product.is_template else 'product'} {product.name}",
        )
        self._activities.detach_product_activities(session, product.id)

        # Baselines point at this product's objects and versions: they go first.
        delete_product_baselines(session, product.id)
        purge_product_comments(session, product.id)
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
            # Revise operation rows point at versions and objects: they go first.
            session.execute(delete(ReviseOperation).where(ReviseOperation.object_id.in_(object_ids)))
            session.execute(delete(ObjectVersion).where(ObjectVersion.object_id.in_(object_ids)))
            session.execute(delete(EngineeringObject).where(EngineeringObject.id.in_(object_ids)))
        session.execute(delete(Dependency).where(Dependency.product_id == product.id))
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
