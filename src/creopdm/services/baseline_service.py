"""Baselines: capture an exact, immutable snapshot of a product's current configuration."""

from __future__ import annotations

import hashlib
import re
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
    BaselineReconstructionError,
    BaselineStructureNotIndexedError,
    BaselineValidationError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.baseline import Baseline, BaselineDependency, BaselineMember
from creopdm.models.dependency import Dependency
from creopdm.models.product_release import ProductRelease
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

TAG_NONE = "NONE"
TAG_PENDING = "PENDING"
TAG_CREATED = "CREATED"
TAG_FAILED = "FAILED"
TAG_NAME_MAX_LENGTH = 200
_TAG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def clean_tag_name(name: str | None) -> str | None:
    """A safe Git tag name, or None when no tag was asked for. Stricter than Git on purpose."""
    text = (name or "").strip()
    if not text:
        return None
    if (
        len(text) > TAG_NAME_MAX_LENGTH
        or not _TAG_NAME_RE.match(text)
        or ".." in text
        or "//" in text
        or "/." in text
        or text.endswith(("/", ".", ".lock"))
    ):
        raise ValidationAppError(
            "The Git tag name may use letters, digits, '.', '_', '-' and '/' (for example "
            "baseline/design-review-01), must start with a letter or digit, and cannot contain "
            "'..' or end with '/', '.' or '.lock'.",
            details={"git_tag": text},
        )
    return text


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

    def list_for_product(
        self, session: Session, product: Product, *, include_archived: bool = False
    ) -> list[Baseline]:
        """Newest first. Archived baselines are hidden from everyday use unless asked for."""
        stmt = select(Baseline).where(Baseline.product_id == product.id)
        if not include_archived:
            stmt = stmt.where(Baseline.status != "ARCHIVED")
        return list(session.scalars(stmt.order_by(Baseline.id.desc())))

    def count_for_product(self, session: Session, product_id: int) -> int:
        """Baselines shown on the product (archived ones are not counted)."""
        return len(
            list(
                session.scalars(
                    select(Baseline.id).where(
                        Baseline.product_id == product_id, Baseline.status != "ARCHIVED"
                    )
                )
            )
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

    def current_configuration(self, session: Session, product: Product) -> list[dict]:
        """The product as it is now, in the same shape as ``members``: every file's CURRENT
        version, resolved before any comparison (so a compare never mixes in stale pointers)."""
        objects = session.scalars(
            select(EngineeringObject)
            .options(joinedload(EngineeringObject.current_version))
            .where(EngineeringObject.product_id == product.id)
            .order_by(EngineeringObject.relative_path.asc())
        )
        out: list[dict] = []
        for obj in objects:
            version = obj.current_version
            if version is None:
                continue
            out.append(
                {
                    "object_uuid": obj.uuid,
                    "version_uuid": version.uuid,
                    "filename": version.filename or obj.filename,
                    "relative_path": version.relative_path or obj.relative_path,
                    "revision": version.revision,
                    "iteration": version.iteration,
                    "display_version": f"{version.revision}.{version.iteration}",
                    "lifecycle_state": version.lifecycle_state or obj.lifecycle_state or "",
                }
            )
        return out

    def compare(
        self,
        session: Session,
        baseline: Baseline,
        other: Baseline | None,
        product: Product,
    ) -> dict:
        """Compare ``baseline`` (the starting point) with ``other`` (or, when None, the current
        configuration) in PDM terms: exact object/version membership, never a Git diff.

        ADDED = only in the target, REMOVED = only in the starting baseline, VERSION_CHANGED =
        the file is in both but at a different exact version, UNCHANGED = the same version.
        Files are matched by object identity, so a rename is not a remove plus an add.
        """
        if other is not None and other.product_id != baseline.product_id:
            raise ValidationAppError(
                "Only baselines of the same product can be compared.",
                details={"from": baseline.uuid, "to": other.uuid},
            )
        left = {row["object_uuid"]: row for row in self.members(session, baseline)}
        right_rows = (
            self.members(session, other)
            if other is not None
            else self.current_configuration(session, product)
        )
        right = {row["object_uuid"]: row for row in right_rows}

        items: list[dict] = []
        for key in sorted(set(left) | set(right)):
            a, b = left.get(key), right.get(key)
            if a is not None and b is None:
                status = "REMOVED"
            elif a is None and b is not None:
                status = "ADDED"
            elif a["version_uuid"] != b["version_uuid"]:
                status = "VERSION_CHANGED"
            else:
                status = "UNCHANGED"
            shown = b or a
            items.append(
                {
                    "object_uuid": key,
                    "filename": shown["filename"],
                    "status": status,
                    "from_version": a["display_version"] if a else None,
                    "to_version": b["display_version"] if b else None,
                    "from_version_uuid": a["version_uuid"] if a else None,
                    "to_version_uuid": b["version_uuid"] if b else None,
                    "from_state": (a["lifecycle_state"] if a else None),
                    "to_state": (b["lifecycle_state"] if b else None),
                }
            )
        order = {"VERSION_CHANGED": 0, "ADDED": 1, "REMOVED": 2, "UNCHANGED": 3}
        items.sort(key=lambda row: (order[row["status"]], row["filename"].casefold()))
        summary = {
            "changed": sum(1 for r in items if r["status"] == "VERSION_CHANGED"),
            "added": sum(1 for r in items if r["status"] == "ADDED"),
            "removed": sum(1 for r in items if r["status"] == "REMOVED"),
            "unchanged": sum(1 for r in items if r["status"] == "UNCHANGED"),
        }
        return {
            "from_baseline": self._compare_side(baseline),
            "to_baseline": self._compare_side(other) if other is not None else self._compare_side(None),
            "summary": summary,
            "items": items,
        }

    @staticmethod
    def _compare_side(baseline: Baseline | None) -> dict:
        if baseline is None:
            return {"kind": "CURRENT", "name": "Current product", "uuid": None,
                    "baseline_type": None, "git_commit_sha": None}
        return {
            "kind": "BASELINE",
            "name": baseline.name,
            "uuid": baseline.uuid,
            "baseline_type": baseline.baseline_type,
            "git_commit_sha": baseline.git_commit_sha,
        }

    # ---- workspace reconstruction ------------------------------------------------------

    @staticmethod
    def workspace_folder(baseline: Baseline) -> str:
        """The folder name for this baseline on a workstation: readable and always unique."""
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", baseline.name).strip("._-") or "baseline"
        return f"{slug[:60]}-{baseline.uuid[:8]}"

    @staticmethod
    def _stored_paths(obj: EngineeringObject, version: ObjectVersion) -> list[str]:
        """Every name the version may be stored under in Git (a rename keeps the old one)."""
        names: list[str] = []
        for raw in (version.relative_path, obj.relative_path, version.filename, obj.filename):
            text = str(raw or "").replace("\\", "/").strip().lstrip("/")
            if text and text not in names:
                names.append(text)
        return names

    def _member_rows(self, session: Session, baseline: Baseline):
        return session.execute(
            select(BaselineMember, ObjectVersion, EngineeringObject)
            .join(ObjectVersion, ObjectVersion.id == BaselineMember.object_version_id)
            .join(EngineeringObject, EngineeringObject.id == BaselineMember.object_id)
            .where(BaselineMember.baseline_id == baseline.id)
            .order_by(BaselineMember.relative_path.asc(), BaselineMember.id.asc())
        ).all()

    def workspace_manifest(self, session: Session, baseline: Baseline, product: Product) -> dict:
        """The exact files a workstation needs to rebuild this baseline.

        Built from the STORED version ids only (never the current version) and checked against
        the vault first: if any member's exact content is missing the whole reconstruction is
        refused and every missing member is named. Nothing is ever substituted.
        """
        rows = self._member_rows(session, baseline)
        if self._git is None or self._config is None:
            raise BaselineReconstructionError("The repository is not available.")
        vault = self._vault_path(product)
        specs: list[str] = []
        spans: list[tuple[int, int]] = []
        for _member, version, obj in rows:
            start = len(specs)
            commit = (version.git_commit_hash or "").strip()
            if commit:
                specs.extend(f"{commit}:{path}" for path in self._stored_paths(obj, version))
            spans.append((start, len(specs)))
        try:
            sizes = self._git.blob_sizes(vault, specs)
        except RepositoryError as exc:
            raise BaselineReconstructionError(
                f"The vault for {product.name} could not be read: {exc.message}",
                details={"product": product.uuid},
            ) from exc
        problems: list[dict] = []
        files: list[dict] = []
        for (member, version, obj), (start, end) in zip(rows, spans):
            shown = f"{version.revision}.{version.iteration}"
            size = next((v for v in sizes[start:end] if v is not None), None)
            if size is None:
                problems.append(
                    self._problem(member.filename, shown, "CONTENT_MISSING", "is not in the vault")
                )
                continue
            if not (version.content_hash or "").strip():
                problems.append(
                    self._problem(member.filename, shown, "NO_CONTENT_HASH", "has no recorded hash")
                )
                continue
            files.append(
                {
                    "object_uuid": obj.uuid,
                    "version_uuid": version.uuid,
                    "filename": member.filename,
                    "relative_path": member.relative_path,
                    "display_version": shown,
                    "lifecycle_state": version.lifecycle_state or member.lifecycle_state or "",
                    "sha256": version.content_hash.strip().lower(),
                    "size": int(size),
                    "content_path": f"/api/baselines/{baseline.uuid}/versions/{version.uuid}/content",
                }
            )
        if problems:
            names = "; ".join(f"{p['file']} {p['version']} {p['reason']}" for p in problems[:5])
            more = f" and {len(problems) - 5} more" if len(problems) > 5 else ""
            raise BaselineReconstructionError(
                f"The baseline cannot be reconstructed: {len(problems)} member"
                f"{'s' if len(problems) != 1 else ''} can't be provided at the exact captured "
                f"version ({names}{more}). No other version is substituted.",
                details={"baseline": baseline.uuid, "problems": problems[:50]},
            )
        return {
            "baseline": {
                "uuid": baseline.uuid,
                "name": baseline.name,
                "baseline_type": baseline.baseline_type,
                "git_commit_sha": baseline.git_commit_sha,
            },
            "product": {
                "uuid": product.uuid,
                "name": product.name,
                "vault_folder": (product.vault_folder or "").strip(),
            },
            "folder": self.workspace_folder(baseline),
            "read_only": True,
            "files": files,
        }

    def member_content(
        self, session: Session, baseline: Baseline, product: Product, version_uuid: str
    ) -> tuple[bytes, str, str]:
        """The exact bytes of one captured version: (bytes, filename, sha256).

        Only a version that is a member of THIS baseline is served, never "latest". The bytes are
        hashed against the recorded SHA-256 before anything is returned, so damaged content is an
        error, not a download.
        """
        wanted = (version_uuid or "").strip()
        match = next(
            (row for row in self._member_rows(session, baseline) if row[1].uuid == wanted), None
        )
        if match is None:
            raise BaselineNotFoundError(
                "That version is not part of this baseline.",
                details={"baseline": baseline.uuid, "version": version_uuid},
            )
        member, version, obj = match
        if self._git is None or self._config is None:
            raise BaselineReconstructionError("The repository is not available.")
        vault = self._vault_path(product)
        commit = (version.git_commit_hash or "").strip()
        shown = f"{version.revision}.{version.iteration}"
        data = None
        if commit:
            for path in self._stored_paths(obj, version):
                try:
                    data = self._git.show_file(vault, path, commit)
                    break
                except RepositoryError:
                    continue
        if data is None:
            raise BaselineReconstructionError(
                f"{member.filename} {shown} is not in the vault. No other version is substituted.",
                details={"baseline": baseline.uuid, "version": wanted, "file": member.filename},
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest != (version.content_hash or "").strip().lower():
            raise BaselineReconstructionError(
                f"{member.filename} {shown} is damaged in the vault (its content does not match "
                "the recorded SHA-256). It was not sent.",
                details={"baseline": baseline.uuid, "version": wanted, "file": member.filename},
            )
        return data, member.filename, digest

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
        git_tag: str | None = None,
        commit: bool = True,
    ) -> Baseline:
        """Capture every file's current version as an immutable, FINALIZED baseline.

        All-or-nothing, serialized per product, and committed while the product lock is still
        held. The same ``operation_id`` always returns the same baseline (retry safety).
        ``commit=False`` (used by a product release) only flushes: the caller owns the one
        transaction that also changes the product, so everything succeeds or fails together.
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
        tag_name = clean_tag_name(git_tag)
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
                git_tag_name=tag_name,
                git_tag_status=TAG_PENDING if tag_name else TAG_NONE,
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
                        "git_tag_name": baseline.git_tag_name,
                    },
                    comment=note,
                )
                if commit:
                    session.commit()
                else:
                    session.flush()
            except IntegrityError as exc:
                if not commit:
                    raise BaselineNameConflictError(
                        f'A baseline named "{clean}" already exists in {product.name}.',
                        details={"name": clean},
                    ) from exc
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
                if commit:
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
            if commit and baseline.git_tag_name:
                # After the commit: the PDM snapshot is already complete and valid. Whatever
                # happens to the tag can only change the tag's own status.
                self._apply_tag(session, product, baseline)
            return baseline

    # ---- administration: archive, global list, integrity ---------------------------------

    STATUS_ARCHIVED = "ARCHIVED"

    def archive(self, session: Session, baseline: Baseline, product: Product) -> Baseline:
        """Hide a finalized baseline from everyday use. Nothing it pins is released, and it can be
        restored. Baselines are never deleted."""
        return self._set_archived(session, baseline, product, archive=True)

    def restore(self, session: Session, baseline: Baseline, product: Product) -> Baseline:
        return self._set_archived(session, baseline, product, archive=False)

    def _set_archived(
        self, session: Session, baseline: Baseline, product: Product, *, archive: bool
    ) -> Baseline:
        wanted = "ARCHIVED" if archive else STATUS_FINALIZED
        needed = STATUS_FINALIZED if archive else "ARCHIVED"
        if baseline.status != needed:
            raise ValidationAppError(
                f'"{baseline.name}" is {baseline.status.title()}, so it cannot be '
                f"{'archived' if archive else 'restored'}.",
                details={"baseline": baseline.uuid, "status": baseline.status},
            )
        user = self._users.get_current_user()
        baseline.status = wanted
        session.flush()
        self._activities.record(
            session,
            ActivityAction.BASELINE_ARCHIVED if archive else ActivityAction.BASELINE_RESTORED,
            user,
            product_id=product.id,
            details={"baseline_uuid": baseline.uuid, "baseline_name": baseline.name},
        )
        session.commit()
        session.refresh(baseline)
        return baseline

    def admin_summary(self, session: Session) -> dict:
        """Counts for the Administration → Baselines diagnostics (always for all baselines)."""
        rows = session.execute(select(Baseline.status, Baseline.baseline_type)).all()
        return {
            "total": len(rows),
            "finalized": sum(1 for status, _t in rows if status == STATUS_FINALIZED),
            "archived": sum(1 for status, _t in rows if status == "ARCHIVED"),
            "release": sum(1 for _s, kind in rows if kind == BASELINE_TYPE_RELEASE),
            "manual": sum(1 for _s, kind in rows if kind == BASELINE_TYPE_MANUAL),
        }

    def admin_list(
        self,
        session: Session,
        *,
        q: str = "",
        baseline_type: str = "",
        status: str = "",
    ) -> list[dict]:
        """Every baseline of every product, newest first, optionally filtered."""
        stmt = (
            select(Baseline, Product)
            .join(Product, Product.id == Baseline.product_id)
            .order_by(Baseline.id.desc())
        )
        if baseline_type.strip():
            stmt = stmt.where(Baseline.baseline_type == baseline_type.strip().upper())
        if status.strip():
            stmt = stmt.where(Baseline.status == status.strip().upper())
        rows = session.execute(stmt).all()
        needle = q.strip().casefold()
        labels = self.release_labels(session, [b.id for b, _p in rows])
        out: list[dict] = []
        for baseline, product in rows:
            if needle and needle not in f"{baseline.name} {product.name} {baseline.created_by}".casefold():
                continue
            out.append(
                {
                    "uuid": baseline.uuid,
                    "name": baseline.name,
                    "description": baseline.description,
                    "product_uuid": product.uuid,
                    "product_name": product.name,
                    "baseline_type": baseline.baseline_type,
                    "release_label": labels.get(baseline.id),
                    "status": baseline.status,
                    "member_count": baseline.member_count,
                    "created_by": baseline.created_by,
                    "created_at": baseline.created_at,
                    "git_commit_sha": baseline.git_commit_sha,
                    "git_tag_name": baseline.git_tag_name,
                }
            )
        return out

    def integrity(
        self, session: Session, baseline: Baseline, product: Product, *, deep: bool = False
    ) -> dict:
        """Is everything this baseline refers to still there and intact? Read only.

        Checks: every member's object and version rows, the exact content in the vault (present,
        and with ``deep`` its SHA-256 matches), the stored Git commit, and the optional tag. A
        problem is reported, never repaired: membership is not changed and nothing newer is
        substituted. ERROR = missing or damaged content/commit; WARNING = tag moved, missing or
        not created; HEALTHY otherwise.
        """
        problems: list[dict] = []
        all_members = list(
            session.scalars(select(BaselineMember).where(BaselineMember.baseline_id == baseline.id))
        )
        rows = self._member_rows(session, baseline)
        if len(rows) != len(all_members):
            present = {member.id for member, _v, _o in rows}
            for member in all_members:
                if member.id not in present:
                    problems.append(
                        self._problem(
                            member.filename,
                            f"{member.revision}.{member.iteration}",
                            "MEMBER_RECORD_MISSING",
                            "its object or version record is missing",
                        )
                    )
        content_ok = 0
        hashes_ok: int | None = 0 if deep else None
        commit_state = "NOT_RECORDED"
        vault_error = None
        if self._git is None or self._config is None:
            vault_error = "the repository is not available"
        else:
            try:
                vault = self._vault_path(product)
                specs: list[str] = []
                spans: list[tuple[int, int]] = []
                for _member, version, obj in rows:
                    start = len(specs)
                    commit = (version.git_commit_hash or "").strip()
                    if commit:
                        specs.extend(f"{commit}:{p}" for p in self._stored_paths(obj, version))
                    spans.append((start, len(specs)))
                sizes = self._git.blob_sizes(vault, specs)
                found_specs: list[tuple[str, ObjectVersion, EngineeringObject]] = []
                for (member, version, obj), (start, end) in zip(rows, spans):
                    shown = f"{version.revision}.{version.iteration}"
                    index = next((i for i in range(start, end) if sizes[i] is not None), None)
                    if index is None:
                        problems.append(
                            self._problem(member.filename, shown, "CONTENT_MISSING", "is not in the vault")
                        )
                        continue
                    if (
                        version.file_size
                        and self._size_is_exact(obj)
                        and int(version.file_size) != sizes[index]
                    ):
                        problems.append(
                            self._problem(
                                member.filename,
                                shown,
                                "CORRUPT",
                                f"is stored with {sizes[index]} bytes but was recorded as {version.file_size}",
                            )
                        )
                        continue
                    content_ok += 1
                    found_specs.append((specs[index], version, member))
                if deep and found_specs:
                    digests = self._git.blob_digests(vault, [spec for spec, _v, _m in found_specs])
                    for (spec, version, member), digest in zip(found_specs, digests):
                        shown = f"{version.revision}.{version.iteration}"
                        if digest is not None and digest == (version.content_hash or "").strip().lower():
                            hashes_ok = (hashes_ok or 0) + 1
                        else:
                            problems.append(
                                self._problem(
                                    member.filename,
                                    shown,
                                    "CORRUPT",
                                    "its content does not match the recorded SHA-256",
                                )
                            )
                if baseline.git_commit_sha:
                    commit_state = (
                        "OK" if self._git.commit_exists(vault, baseline.git_commit_sha) else "MISSING"
                    )
                    if commit_state == "MISSING":
                        problems.append(
                            {
                                "code": "COMMIT_MISSING",
                                "file": "",
                                "version": "",
                                "reason": f"the stored repository commit {baseline.git_commit_sha[:12]} no longer exists",
                            }
                        )
            except RepositoryError as exc:
                vault_error = exc.message
        if vault_error:
            problems.append(
                {"code": "VAULT_UNREADABLE", "file": "", "version": "", "reason": vault_error}
            )
        tag = self.check_tag(product, baseline)
        errors = [p for p in problems]
        status = "ERROR" if errors else "HEALTHY"
        if status == "HEALTHY" and tag["state"] in {"MOVED", "MISSING", "NOT_CREATED"}:
            status = "WARNING"
        return {
            "baseline_uuid": baseline.uuid,
            "name": baseline.name,
            "product_uuid": product.uuid,
            "product_name": product.name,
            "baseline_type": baseline.baseline_type,
            "baseline_status": baseline.status,
            "status": status,
            "deep": bool(deep),
            "members": len(all_members),
            "versions_ok": len(rows),
            "content_ok": content_ok,
            "hashes_ok": hashes_ok,
            "commit": commit_state,
            "stored_commit": baseline.git_commit_sha,
            "tag_state": tag["state"],
            "tag_name": tag["tag_name"],
            "tag_points_at": tag["tag_points_at"],
            "tag_warning": tag["warning"],
            "problems": problems[:100],
            "problem_count": len(problems),
            "checked_at": datetime.now(timezone.utc),
        }

    def integrity_all(self, session: Session) -> list[dict]:
        """A quick (no hashing) check of every baseline, so an admin sees the whole picture."""
        out: list[dict] = []
        for baseline in session.scalars(select(Baseline).order_by(Baseline.id.desc())):
            product = session.get(Product, baseline.product_id)
            if product is None:
                continue
            out.append(self.integrity(session, baseline, product, deep=False))
        return out

    # ---- product releases ---------------------------------------------------------------

    def create_release(
        self, session: Session, product: Product, user_name: str, *, tag: bool = False
    ) -> ProductRelease:
        """Record release R<n> of ``product`` with its strict Release baseline.

        Called inside the Promote-to-Released transaction (nothing is committed here). A product
        with no checked-in file has nothing to capture and is released without a baseline. Any
        other problem (an unresolved required dependency, missing Where Used, missing or damaged
        content) refuses the release, and the caller rolls the whole promotion back.
        """
        last = session.scalar(
            select(ProductRelease.number)
            .where(ProductRelease.product_id == product.id)
            .order_by(ProductRelease.number.desc())
            .limit(1)
        )
        number = int(last or 0) + 1
        label = f"R{number}"
        baseline = None
        try:
            with self._locks.acquire(product.uuid):
                baseline = self.create(
                    session,
                    product,
                    f"{product.name}-{label}",
                    f"Release {label} of {product.name}",
                    baseline_type=BASELINE_TYPE_RELEASE,
                    # Each product has its own repository, so the release number is enough.
                    git_tag=f"release/{label}" if tag else None,
                    commit=False,
                )
        except BaselineEmptyError:
            baseline = None
        except (BaselineValidationError, BaselineStructureNotIndexedError) as exc:
            raise BaselineValidationError(
                f"{product.name} cannot be released. {exc.message}", details=exc.details
            ) from exc
        release = ProductRelease(
            uuid=str(uuidlib.uuid4()),
            product_id=product.id,
            number=number,
            label=label,
            baseline_id=baseline.id if baseline is not None else None,
            released_by=user_name,
        )
        session.add(release)
        session.flush()
        return release

    def apply_release_tag(
        self, session: Session, product: Product, release: ProductRelease
    ) -> Baseline | None:
        """Create the release's Git tag once the promotion has committed. Never raises: a failed
        tag is recorded on the baseline (FAILED) and can be retried; the release stands."""
        if release.baseline_id is None:
            return None
        baseline = session.get(Baseline, release.baseline_id)
        if baseline is None or not baseline.git_tag_name:
            return baseline
        with self._locks.acquire(product.uuid):
            self._apply_tag(session, product, baseline)
        return baseline

    def release_labels(self, session: Session, baseline_ids: list[int]) -> dict[int, str]:
        """``{baseline id: "R2"}`` for the baselines that are a product release."""
        if not baseline_ids:
            return {}
        rows = session.execute(
            select(ProductRelease.baseline_id, ProductRelease.label).where(
                ProductRelease.baseline_id.in_(baseline_ids)
            )
        ).all()
        return {int(bid): str(label) for bid, label in rows}

    def list_releases(self, session: Session, product: Product) -> list[dict]:
        """The product's releases, newest first, each with its exact baseline."""
        rows = session.execute(
            select(ProductRelease, Baseline)
            .outerjoin(Baseline, Baseline.id == ProductRelease.baseline_id)
            .where(ProductRelease.product_id == product.id)
            .order_by(ProductRelease.number.desc())
        ).all()
        return [
            {
                "uuid": release.uuid,
                "number": release.number,
                "label": release.label,
                "released_by": release.released_by,
                "released_at": release.released_at,
                "baseline_uuid": baseline.uuid if baseline is not None else None,
                "baseline_name": baseline.name if baseline is not None else None,
                "member_count": baseline.member_count if baseline is not None else 0,
                "git_tag_name": baseline.git_tag_name if baseline is not None else None,
                "git_tag_status": (baseline.git_tag_status if baseline is not None else "NONE"),
                "git_tag_error": baseline.git_tag_error if baseline is not None else None,
            }
            for release, baseline in rows
        ]

    # ---- optional Git tag -------------------------------------------------------------

    def retry_tag(self, session: Session, baseline: Baseline, product: Product) -> Baseline:
        """Try again to create a tag that is pending or failed. Never moves an existing tag."""
        if not baseline.git_tag_name:
            raise ValidationAppError("This baseline has no Git tag to create.")
        if baseline.git_tag_status == TAG_CREATED:
            return baseline
        with self._locks.acquire(product.uuid):
            session.refresh(baseline)
            self._apply_tag(session, product, baseline)
        return baseline

    def _vault_path(self, product: Product):
        return self._config.workspace_for_product(
            (product.vault_folder or "").strip() or product.uuid
        )

    def _apply_tag(self, session: Session, product: Product, baseline: Baseline) -> None:
        """Create the tag on the stored commit and record the outcome. Never raises: a failed tag
        leaves the baseline FINALIZED with its commit intact and the tag retryable."""
        status, error = TAG_FAILED, None
        try:
            if self._git is None or self._config is None or not baseline.git_commit_sha:
                raise RepositoryError("The repository is not available for tagging.")
            vault = self._vault_path(product)
            existing = self._git.tag_target(vault, baseline.git_tag_name)
            if existing is None:
                self._git.create_tag(vault, baseline.git_tag_name, baseline.git_commit_sha)
                status = TAG_CREATED
            elif existing == baseline.git_commit_sha:
                status = TAG_CREATED
            else:
                error = (
                    f'The tag "{baseline.git_tag_name}" already exists and points at '
                    f"{existing[:12]}. CreoPDM never moves a tag."
                )
        except Exception as exc:  # noqa: BLE001 - tagging must never undo a valid baseline
            error = str(getattr(exc, "message", None) or exc)[:500] or "Tag creation failed."
            logger.warning("Git tag %s failed for baseline %s: %s", baseline.git_tag_name, baseline.uuid, error)
        try:
            baseline.git_tag_status = status
            baseline.git_tag_error = None if status == TAG_CREATED else error
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.exception("Could not record the tag status for baseline %s", baseline.uuid)
        else:
            session.refresh(baseline)

    def check_tag(self, product: Product, baseline: Baseline) -> dict:
        """Compare the tag in the repository with the stored commit (read only).

        A moved tag is reported, never followed: the stored commit stays what it was.
        """
        out = {
            "tag_name": baseline.git_tag_name,
            "tag_status": baseline.git_tag_status,
            "stored_commit": baseline.git_commit_sha,
            "tag_points_at": None,
            "state": "NO_TAG",
            "warning": None,
        }
        if not baseline.git_tag_name:
            return out
        target = None
        if self._git is not None and self._config is not None:
            try:
                target = self._git.tag_target(self._vault_path(product), baseline.git_tag_name)
            except Exception:  # noqa: BLE001
                target = None
        out["tag_points_at"] = target
        if target is not None and target == baseline.git_commit_sha:
            out["state"] = "OK"
        elif target is not None:
            out["state"] = "MOVED"
            out["warning"] = (
                f'Integrity warning: the tag "{baseline.git_tag_name}" now points at '
                f"{target[:12]}, but this baseline was made at {str(baseline.git_commit_sha)[:12]}. "
                "The stored commit is unchanged and is still the record."
            )
            logger.warning(
                "Baseline %s: tag %s moved from %s to %s",
                baseline.uuid, baseline.git_tag_name, baseline.git_commit_sha, target,
            )
        elif baseline.git_tag_status == TAG_CREATED:
            out["state"] = "MISSING"
            out["warning"] = (
                f'Integrity warning: the tag "{baseline.git_tag_name}" no longer exists in the '
                "repository. The stored commit is unchanged."
            )
        else:
            out["state"] = "NOT_CREATED"
        return out

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
