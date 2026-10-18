"""Baselines: capture an exact, immutable snapshot of a product's current configuration."""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from creopdm.constants import ActivityAction, DependencyType, LifecycleState
from creopdm.exceptions import (
    BaselineEmptyError,
    BaselineImmutableError,
    BaselineNameConflictError,
    BaselineNotFoundError,
    BaselineStructureNotIndexedError,
    BaselineValidationError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.baseline import Baseline, BaselineDependency, BaselineMember
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from creopdm.models.product import Product
from creopdm.services.activity_service import ActivityService
from creopdm.product_state import (
    ensure_product_allows,
    product_is_archived,
    product_state_value,
)
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.utils.identity import CurrentUserProvider

logger = get_logger("baselines")

NAME_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 2000
BASELINE_TYPE_MANUAL = "MANUAL"
# A release baseline is validated STRICTLY: nothing may be unresolved or unindexed.
BASELINE_TYPE_RELEASE = "RELEASE"
BASELINE_TYPES = (BASELINE_TYPE_MANUAL, BASELINE_TYPE_RELEASE)
STATUS_DRAFT = "DRAFT"
STATUS_FINALIZED = "FINALIZED"
# Edges whose absence would make the configuration impossible to rebuild; a plain REFERENCE or an
# UNKNOWN link is recorded but is not required.
REQUIRED_DEPENDENCY_TYPES = frozenset(
    {
        DependencyType.ASSEMBLY_MEMBER.value,
        DependencyType.DRAWING_MODEL.value,
        DependencyType.SKELETON.value,
        DependencyType.MERGE.value,
    }
)


_STRUCTURE_OBJECT_TYPES = frozenset({"CREO_ASSEMBLY", "CREO_DRAWING"})


def clean_name(name: str | None) -> str:
    text = " ".join((name or "").split())
    if not text:
        raise ValidationAppError("A baseline name is required.")
    if len(text) > NAME_MAX_LENGTH:
        raise ValidationAppError(f"The baseline name is too long (max {NAME_MAX_LENGTH} characters).")
    return text


def clean_description(description: str | None) -> str | None:
    text = (description or "").strip()
    if len(text) > DESCRIPTION_MAX_LENGTH:
        raise ValidationAppError(
            f"The description is too long (max {DESCRIPTION_MAX_LENGTH} characters)."
        )
    return text or None


class BaselineService:
    def __init__(
        self,
        locks: ProductLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
        git: GitService | None = None,
        config=None,
    ) -> None:
        self._locks = locks
        self._activities = activities
        self._users = users
        self._git = git
        self._config = config

    # ---- reads -------------------------------------------------------------------------

    def list_for_product(self, session: Session, product: Product) -> list[Baseline]:
        """Newest first."""
        return list(
            session.scalars(
                select(Baseline)
                .where(Baseline.product_id == product.id)
                .order_by(Baseline.id.desc())
            )
        )

    def count_for_product(self, session: Session, product_id: int) -> int:
        return len(
            list(session.scalars(select(Baseline.id).where(Baseline.product_id == product_id)))
        )

    def get(self, session: Session, baseline_uuid: str) -> Baseline:
        row = session.scalar(
            select(Baseline)
            .options(selectinload(Baseline.members))
            .where(Baseline.uuid == (baseline_uuid or "").strip())
        )
        if row is None:
            raise BaselineNotFoundError("Baseline not found.", details={"uuid": baseline_uuid})
        return row

    def members(self, session: Session, baseline: Baseline) -> list[dict]:
        """The baseline's exact members, resolved through the STORED version ids.

        Never through the object's current version: after later check-ins, revisions or a rename
        this still answers with what was captured. ``status`` compares to the current version only
        for information.
        """
        current = aliased(ObjectVersion)
        rows = session.execute(
            select(BaselineMember, ObjectVersion, EngineeringObject, current)
            .join(ObjectVersion, ObjectVersion.id == BaselineMember.object_version_id)
            .join(EngineeringObject, EngineeringObject.id == BaselineMember.object_id)
            .outerjoin(current, current.id == EngineeringObject.current_version_id)
            .where(BaselineMember.baseline_id == baseline.id)
            .order_by(BaselineMember.relative_path.asc(), BaselineMember.id.asc())
        ).all()
        out: list[dict] = []
        for member, version, obj, cur in rows:
            same = obj.current_version_id == member.object_version_id
            out.append(
                {
                    "object_uuid": obj.uuid,
                    "version_uuid": version.uuid,
                    # Name and path as they were when the baseline was made.
                    "filename": member.filename,
                    "relative_path": member.relative_path,
                    "object_type": member.object_type,
                    # Everything else from the exact captured version row.
                    "revision": version.revision,
                    "iteration": version.iteration,
                    "display_version": f"{version.revision}.{version.iteration}",
                    "lifecycle_state": version.lifecycle_state or member.lifecycle_state or "",
                    "content_hash": version.content_hash,
                    "current_version_uuid": cur.uuid if cur is not None else None,
                    "current_display_version": (
                        f"{cur.revision}.{cur.iteration}" if cur is not None else None
                    ),
                    "status": "SAME" if same else "OUT_OF_DATE",
                }
            )
        return out

    def dependencies(self, session: Session, baseline: Baseline) -> list[dict]:
        """The structure captured with the baseline, read from the STORED rows only.

        Parent and child versions come from the stored version ids. Nothing is recomputed from
        the live dependency table or from the objects' latest versions.
        """
        parent_version = aliased(ObjectVersion)
        child_version = aliased(ObjectVersion)
        parent_member = aliased(BaselineMember)
        rows = session.execute(
            select(BaselineDependency, parent_version, child_version, parent_member)
            .join(parent_version, parent_version.id == BaselineDependency.parent_object_version_id)
            .outerjoin(
                child_version, child_version.id == BaselineDependency.child_object_version_id
            )
            .join(
                parent_member,
                (parent_member.baseline_id == BaselineDependency.baseline_id)
                & (parent_member.object_id == BaselineDependency.parent_object_id),
            )
            .where(BaselineDependency.baseline_id == baseline.id)
            .order_by(parent_member.relative_path.asc(), BaselineDependency.child_filename.asc())
        ).all()
        out: list[dict] = []
        for edge, parent, child, member in rows:
            out.append(
                {
                    "parent_filename": member.filename,
                    "parent_version_uuid": parent.uuid,
                    "parent_display_version": f"{parent.revision}.{parent.iteration}",
                    "child_filename": edge.child_filename,
                    "child_version_uuid": child.uuid if child is not None else None,
                    "child_display_version": (
                        f"{child.revision}.{child.iteration}" if child is not None else None
                    ),
                    "dependency_type": edge.dependency_type,
                    "quantity": edge.quantity,
                    "required": bool(edge.required),
                    "resolved": bool(edge.resolved),
                }
            )
        return out

    # ---- create ------------------------------------------------------------------------

    def create(
        self,
        session: Session,
        product: Product,
        name: str | None,
        description: str | None = None,
        operation_id: str | None = None,
        accept_missing_structure: bool = False,
        baseline_type: str | None = None,
    ) -> Baseline:
        """Capture every file's current version as an immutable, FINALIZED baseline.

        All-or-nothing, serialized per product, and committed while the product lock is still
        held. The same ``operation_id`` always returns the same baseline (retry safety).
        """
        op_id = (operation_id or "").strip() or None
        replay = self._replay(session, product, op_id)
        if replay is not None:
            return replay
        clean = clean_name(name)
        note = clean_description(description)
        kind = (baseline_type or BASELINE_TYPE_MANUAL).strip().upper()
        if kind not in BASELINE_TYPES:
            raise ValidationAppError(
                f"Unknown baseline type. Use one of: {', '.join(BASELINE_TYPES)}.",
                details={"baseline_type": baseline_type},
            )
        strict = kind == BASELINE_TYPE_RELEASE
        user = self._users.get_current_user()

        with self._locks.acquire(product.uuid):
            replay = self._replay(session, product, op_id)
            if replay is not None:
                return replay
            self._require_unique_name(session, product, clean)
            self._require_product_allows_baseline(product)
            objects = list(
                session.scalars(
                    select(EngineeringObject)
                    .options(joinedload(EngineeringObject.current_version))
                    .where(EngineeringObject.product_id == product.id)
                    .order_by(EngineeringObject.relative_path.asc())
                )
            )
            captured = [obj for obj in objects if obj.current_version is not None]
            if not captured:
                raise BaselineEmptyError(
                    f"{product.name} has no files with a checked-in version to baseline.",
                    details={"product": product.uuid},
                )
            self._validate_content(product, captured)
            commit_sha = self._vault_commit(product)
            structure_indexed = self._structure_indexed(session, product, captured)
            if strict:
                self._require_strict_structure(session, product, captured, structure_indexed)
            if not structure_indexed and not accept_missing_structure:
                raise BaselineStructureNotIndexedError(
                    "Where Used has not been built for this product, so this baseline would not "
                    "record which parts its assemblies and drawings use. Rebuild Where Used first, "
                    "or confirm that you want a baseline without structure.",
                    details={"product": product.uuid},
                )
            now = datetime.now(timezone.utc)
            # Capture, then finalize, inside this one transaction: members may be written only
            # while the baseline is a draft; once finalized nothing about it can change.
            baseline = Baseline(
                uuid=str(uuidlib.uuid4()),
                product_id=product.id,
                name=clean,
                description=note,
                baseline_type=kind,
                status=STATUS_DRAFT,
                member_count=0,
                created_by=user.user_name,
                operation_id=op_id,
                structure_indexed=structure_indexed,
                git_commit_sha=commit_sha,
            )
            try:
                session.add(baseline)
                session.flush()
                session.add_all(self._members(baseline, captured))
                session.flush()
                edges = self._dependencies(session, baseline, product, captured)
                session.add_all(edges)
                session.flush()
                baseline.dependency_count = len(edges)
                baseline.unresolved_dependency_count = sum(1 for e in edges if not e.resolved)
                baseline.status = STATUS_FINALIZED
                baseline.member_count = len(captured)
                baseline.finalized_by = user.user_name
                baseline.finalized_at = now
                session.flush()
                self._activities.record(
                    session,
                    ActivityAction.BASELINE_CREATED,
                    user,
                    product_id=product.id,
                    details={
                        "baseline_uuid": baseline.uuid,
                        "baseline_name": baseline.name,
                        "baseline_type": baseline.baseline_type,
                        "member_count": baseline.member_count,
                        "dependency_count": baseline.dependency_count,
                        "unresolved_dependency_count": baseline.unresolved_dependency_count,
                        "structure_indexed": baseline.structure_indexed,
                        "git_commit_sha": baseline.git_commit_sha,
                    },
                    comment=note,
                )
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                # Same operation id, or the same name, won a race: answer from what is stored.
                replay = self._replay(session, product, op_id)
                if replay is not None:
                    return replay
                raise BaselineNameConflictError(
                    f'A baseline named "{clean}" already exists in {product.name}.',
                    details={"name": clean},
                ) from exc
            except Exception:
                session.rollback()
                logger.exception("Baseline create failed for %s", product.uuid)
                raise
            logger.info(
                "Created baseline %s (%s members) for product %s",
                baseline.uuid,
                baseline.member_count,
                product.uuid,
            )
            session.refresh(baseline)
            return baseline

    # ---- membership is closed once finalized -------------------------------------------
    # A single choke point: these are the only ways code could try to change what a baseline
    # holds, and a finalized baseline refuses all of them (the model layer enforces it too).

    @staticmethod
    def _refuse_change(baseline: Baseline) -> None:
        raise BaselineImmutableError(
            "A finalized baseline can never be changed. Create a new baseline for a different "
            "configuration.",
            details={"baseline": baseline.uuid, "status": baseline.status},
        )

    def add_member(self, session: Session, baseline: Baseline, *_args, **_kwargs) -> None:
        self._refuse_change(baseline)

    def remove_member(self, session: Session, baseline: Baseline, *_args, **_kwargs) -> None:
        self._refuse_change(baseline)

    def replace_member_version(
        self, session: Session, baseline: Baseline, *_args, **_kwargs
    ) -> None:
        self._refuse_change(baseline)

    def replace_members(self, session: Session, baseline: Baseline, *_args, **_kwargs) -> None:
        """Rewrite the whole membership (also refused)."""
        self._refuse_change(baseline)

    # ---- helpers -----------------------------------------------------------------------

    def _replay(self, session: Session, product: Product, op_id: str | None) -> Baseline | None:
        if op_id is None:
            return None
        found = session.scalar(select(Baseline).where(Baseline.operation_id == op_id))
        if found is None:
            return None
        if found.product_id != product.id:
            raise ValidationAppError(
                "That operation id was already used for a different product.",
                details={"operation_id": op_id},
            )
        return found

    def _require_unique_name(self, session: Session, product: Product, name: str) -> None:
        wanted = name.casefold()
        for existing in session.scalars(
            select(Baseline.name).where(Baseline.product_id == product.id)
        ):
            if str(existing).casefold() == wanted:
                raise BaselineNameConflictError(
                    f'A baseline named "{existing}" already exists in {product.name}.',
                    details={"name": existing},
                )

    @staticmethod
    def _require_product_allows_baseline(product: Product) -> None:
        """A baseline only reads the configuration, so it is allowed in every state that lets the
        product be viewed, except Archived."""
        if product_is_archived(product):
            raise BaselineValidationError(
                f"{product.name} is Archived and cannot be baselined.",
                details={"product": product.uuid, "state": product_state_value(product)},
            )
        ensure_product_allows(product, "view", action="create a baseline")

    def _validate_content(self, product: Product, captured: list[EngineeringObject]) -> None:
        """Every captured version must really exist in the vault, with the size that was stored.

        One failing file refuses the whole baseline (nothing is created) and the answer names
        every file that failed, so it can be repaired and the baseline retried.
        """
        problems: list[dict] = []
        checkable: list[tuple[EngineeringObject, ObjectVersion, str]] = []
        for obj in captured:
            version = obj.current_version
            name = version.filename or obj.filename
            shown = f"{version.revision}.{version.iteration}"
            if not (version.git_commit_hash or "").strip():
                problems.append(self._problem(name, shown, "NO_STORED_COMMIT", "has no stored commit"))
            elif not (version.content_hash or "").strip():
                problems.append(self._problem(name, shown, "NO_CONTENT_HASH", "has no recorded content hash"))
            else:
                checkable.append((obj, version, name))
        if checkable and self._git is not None and self._config is not None:
            vault = self._config.workspace_for_product(
                (product.vault_folder or "").strip() or product.uuid
            )
            # The stored path can differ from the current one (a rename), so every known name is
            # tried, the same candidates a revert uses.
            specs: list[str] = []
            spans: list[tuple[int, int]] = []
            for obj, version, _name in checkable:
                names: list[str] = []
                for raw in (version.relative_path, obj.relative_path, version.filename, obj.filename):
                    text = str(raw or "").replace("\\", "/").strip().lstrip("/")
                    if text and text not in names:
                        names.append(text)
                start = len(specs)
                specs.extend(f"{version.git_commit_hash}:{text}" for text in names)
                spans.append((start, len(specs)))
            try:
                sizes = self._git.blob_sizes(vault, specs)
            except RepositoryError as exc:
                raise BaselineValidationError(
                    f"The vault for {product.name} could not be checked: {exc.message}",
                    details={"product": product.uuid},
                ) from exc
            for (obj, version, name), (start, end) in zip(checkable, spans):
                shown = f"{version.revision}.{version.iteration}"
                size = next((value for value in sizes[start:end] if value is not None), None)
                if size is None:
                    problems.append(
                        self._problem(name, shown, "CONTENT_MISSING", "is not in the vault")
                    )
                elif (
                    version.file_size
                    and self._size_is_exact(obj)
                    and int(version.file_size) != size
                ):
                    problems.append(
                        self._problem(
                            name,
                            shown,
                            "CONTENT_SIZE_MISMATCH",
                            f"is stored with {size} bytes but was recorded as {version.file_size}",
                        )
                    )
        if not problems:
            return
        shown_names = "; ".join(f"{p['file']} {p['version']} {p['reason']}" for p in problems[:5])
        more = f" and {len(problems) - 5} more" if len(problems) > 5 else ""
        raise BaselineValidationError(
            f"No baseline was created: {len(problems)} file{'s' if len(problems) != 1 else ''} "
            f"failed validation ({shown_names}{more}).",
            details={"product": product.uuid, "problems": problems[:50]},
        )

    def _vault_commit(self, product: Product) -> str | None:
        """The product repository's HEAD as a full SHA, read inside the product lock so no check-in
        can move it between the validation and the capture."""
        if self._git is None or self._config is None:
            return None
        vault = self._config.workspace_for_product(
            (product.vault_folder or "").strip() or product.uuid
        )
        try:
            sha = self._git.get_head(vault).strip().lower()
        except RepositoryError as exc:
            raise BaselineValidationError(
                f"The repository state of {product.name} could not be read: {exc.message}",
                details={"product": product.uuid},
            ) from exc
        if len(sha) < 40 or any(ch not in "0123456789abcdef" for ch in sha):
            raise BaselineValidationError(
                f"The repository state of {product.name} could not be read (no commit).",
                details={"product": product.uuid},
            )
        return sha

    @staticmethod
    def _require_strict_structure(
        session: Session,
        product: Product,
        captured: list[EngineeringObject],
        structure_indexed: bool,
    ) -> None:
        """STRICT policy (release baselines): a missing structure index or any unresolved
        required dependency blocks finalization. Nothing is omitted and nothing is waived."""
        if not structure_indexed:
            raise BaselineValidationError(
                "No release baseline was created: Where Used has not been built for this product, "
                "so its required dependencies cannot be verified. Rebuild Where Used first.",
                details={"product": product.uuid, "problems": [{"code": "STRUCTURE_NOT_INDEXED"}]},
            )
        members = {obj.id: obj for obj in captured}
        problems: list[dict] = []
        edges = session.scalars(
            select(Dependency)
            .where(
                Dependency.product_id == product.id,
                Dependency.dependency_type.in_(sorted(REQUIRED_DEPENDENCY_TYPES)),
            )
            .order_by(Dependency.id.asc())
        )
        for edge in edges:
            parent = members.get(edge.parent_object_id)
            if parent is None or edge.child_object_id in members:
                continue
            child = session.get(EngineeringObject, edge.child_object_id)
            problems.append(
                {
                    "code": "UNRESOLVED_REQUIRED_DEPENDENCY",
                    "parent": parent.current_version.filename or parent.filename,
                    "child": child.filename if child is not None else "(unknown)",
                    "dependency_type": edge.dependency_type,
                }
            )
        if not problems:
            return
        shown = "; ".join(f"{p['parent']} needs {p['child']}" for p in problems[:5])
        more = f" and {len(problems) - 5} more" if len(problems) > 5 else ""
        raise BaselineValidationError(
            f"No release baseline was created: {len(problems)} required "
            f"dependenc{'ies are' if len(problems) != 1 else 'y is'} unresolved, with no checked-in "
            f"version ({shown}{more}).",
            details={"product": product.uuid, "problems": problems[:50]},
        )

    @staticmethod
    def _size_is_exact(obj: EngineeringObject) -> bool:
        """Binary formats are stored byte for byte, so their size must match. Text formats can be
        re-encoded by Git's line-ending settings, so only their presence is checked."""
        kind = str(obj.object_type or "")
        return kind.startswith("CREO_") or kind == "PDF"

    @staticmethod
    def _problem(file: str, version: str, code: str, reason: str) -> dict:
        return {"file": file, "version": version, "code": code, "reason": reason}

    @staticmethod
    def _structure_indexed(
        session: Session, product: Product, captured: list[EngineeringObject]
    ) -> bool:
        """False only when there is structure to capture (an assembly or drawing) but the product
        has no dependency rows at all, i.e. Where Used was never built."""
        if not any(obj.object_type in _STRUCTURE_OBJECT_TYPES for obj in captured):
            return True
        return (
            session.scalar(
                select(Dependency.id).where(Dependency.product_id == product.id).limit(1)
            )
            is not None
        )

    @staticmethod
    def _dependencies(
        session: Session,
        baseline: Baseline,
        product: Product,
        captured: list[EngineeringObject],
    ) -> list[BaselineDependency]:
        """Freeze the product's structure edges against the versions being captured.

        Both ends are resolved through the captured members: the parent and child versions are
        the exact ones in this baseline. A child with no captured version stays in the baseline
        as an unresolved edge (never dropped, never replaced by "latest").
        """
        by_object = {obj.id: obj for obj in captured}
        edges = session.scalars(
            select(Dependency)
            .where(Dependency.product_id == product.id)
            .order_by(Dependency.id.asc())
        )
        child_names: dict[int, str] = {}
        out: list[BaselineDependency] = []
        for edge in edges:
            parent = by_object.get(edge.parent_object_id)
            if parent is None:
                continue  # the parent is not in the configuration, so the edge is not either
            child = by_object.get(edge.child_object_id)
            if child is not None:
                child_name = child.current_version.filename or child.filename
            else:
                if edge.child_object_id not in child_names:
                    other = session.get(EngineeringObject, edge.child_object_id)
                    child_names[edge.child_object_id] = other.filename if other else "(unknown)"
                child_name = child_names[edge.child_object_id]
            kind = edge.dependency_type or DependencyType.UNKNOWN.value
            out.append(
                BaselineDependency(
                    baseline_id=baseline.id,
                    parent_object_id=parent.id,
                    parent_object_version_id=parent.current_version.id,
                    child_object_id=edge.child_object_id,
                    child_object_version_id=child.current_version.id if child is not None else None,
                    child_filename=child_name,
                    dependency_type=kind,
                    quantity=edge.quantity if edge.quantity is not None else 1.0,
                    required=kind in REQUIRED_DEPENDENCY_TYPES,
                    resolved=child is not None,
                )
            )
        return out

    @staticmethod
    def _members(baseline: Baseline, objects: list[EngineeringObject]) -> list[BaselineMember]:
        members: list[BaselineMember] = []
        for obj in objects:
            version = obj.current_version
            assert version is not None
            members.append(
                BaselineMember(
                    baseline_id=baseline.id,
                    object_id=obj.id,
                    object_version_id=version.id,
                    filename=version.filename or obj.filename,
                    relative_path=version.relative_path or obj.relative_path,
                    object_type=obj.object_type,
                    revision=version.revision,
                    iteration=version.iteration,
                    # The state of THIS version (a Released A.3 stays Released after B.1).
                    lifecycle_state=version.lifecycle_state
                    or obj.lifecycle_state
                    or LifecycleState.IN_WORK.value,
                    content_hash=version.content_hash,
                )
            )
        return members
