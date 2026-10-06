"""Audit trail for important PDM actions (Utilities → Audit log)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from creopdm.constants import ActivityAction
from creopdm.models.activity import Activity
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.utils.identity import UserIdentity

AUDIT_PAGE_SIZE = 100

# Keys never stored in audit details_json.
_REDACT_DETAIL_KEYS = frozenset(
    {
        "password",
        "smtp_password",
        "token",
        "access_token",
        "api_secret",
        "secret",
        "private_key",
        "session_token",
    }
)

ACTION_LABELS: dict[str, str] = {
    ActivityAction.PRODUCT_CREATED.value: "Product created",
    ActivityAction.PRODUCT_UPDATED.value: "Product updated",
    ActivityAction.PRODUCT_DELETED.value: "Product deleted",
    ActivityAction.STATE_CHANGED.value: "Product state changed",
    ActivityAction.OBJECT_ADDED.value: "Object added",
    ActivityAction.OBJECT_REMOVED.value: "Object removed",
    ActivityAction.WORKSPACE_CLEARED.value: "Workspace cleared",
    ActivityAction.CHECKED_OUT.value: "Checked out",
    ActivityAction.CHECKOUT_CANCELLED.value: "Checkout cancelled",
    ActivityAction.CHECKOUT_OVERRIDE.value: "Checkout override",
    ActivityAction.CHECKED_IN.value: "Checked in",
    ActivityAction.VERSION_RESTORED.value: "Version restored",
    ActivityAction.VAULT_HISTORY_COMPACTED.value: "Vault history compacted",
    ActivityAction.PRODUCT_DB_REBUILT.value: "Product DB rebuilt",
    ActivityAction.USER_CREATED.value: "User created",
    ActivityAction.USER_DISABLED.value: "User disabled",
    ActivityAction.USER_ENABLED.value: "User enabled",
    ActivityAction.USER_LOGIN.value: "Signed in",
    ActivityAction.USER_LOGOUT.value: "Signed out",
    ActivityAction.LOGIN_FAILED.value: "Sign-in failed",
    ActivityAction.ROLE_CHANGED.value: "Role changed",
    ActivityAction.MEMBERSHIP_CHANGED.value: "Membership changed",
    ActivityAction.SYSTEM_SETTING_CHANGED.value: "System setting changed",
}

# Utilities → Audit Event filter: pathway order; rarer admin ops last.
# Values may be a single action or comma-joined group (e.g. Sign in/Sign out).
AUDIT_ACTION_FILTER_CHOICES: list[tuple[str, str]] = [
    (
        f"{ActivityAction.USER_LOGIN.value},{ActivityAction.USER_LOGOUT.value}",
        "Sign in/Sign out",
    ),
    (ActivityAction.LOGIN_FAILED.value, "Sign-in failed"),
    (ActivityAction.USER_CREATED.value, "User created"),
    (ActivityAction.ROLE_CHANGED.value, "Role changed"),
    (ActivityAction.MEMBERSHIP_CHANGED.value, "Membership changed"),
    (ActivityAction.USER_ENABLED.value, "User enabled"),
    (ActivityAction.USER_DISABLED.value, "User disabled"),
    (ActivityAction.PRODUCT_CREATED.value, "Product created"),
    (ActivityAction.PRODUCT_UPDATED.value, "Product updated"),
    (ActivityAction.STATE_CHANGED.value, "Product state changed"),
    (ActivityAction.OBJECT_ADDED.value, "Object added"),
    (
        f"{ActivityAction.CHECKED_IN.value},{ActivityAction.CHECKED_OUT.value}",
        "Check in/Check out",
    ),
    (ActivityAction.CHECKOUT_CANCELLED.value, "Checkout cancelled"),
    (ActivityAction.CHECKOUT_OVERRIDE.value, "Checkout override"),
    (ActivityAction.OBJECT_REMOVED.value, "Object removed"),
    (ActivityAction.WORKSPACE_CLEARED.value, "Workspace cleared"),
    (ActivityAction.VERSION_RESTORED.value, "Version restored"),
    (ActivityAction.PRODUCT_DELETED.value, "Product deleted"),
    (ActivityAction.SYSTEM_SETTING_CHANGED.value, "System setting changed"),
    (ActivityAction.VAULT_HISTORY_COMPACTED.value, "Vault history compacted"),
    (ActivityAction.PRODUCT_DB_REBUILT.value, "Product DB rebuilt"),
]


def redact_audit_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop or mask secret-bearing fields before persisting audit event_data."""
    if not details:
        return None
    out: dict[str, Any] = {}
    for key, value in details.items():
        low = str(key).lower()
        if low in _REDACT_DETAIL_KEYS or any(
            part in low for part in ("password", "secret", "token")
        ):
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            nested = redact_audit_details(value)
            out[key] = nested if nested is not None else {}
        else:
            out[key] = value
    return out


def action_label(action: str) -> str:
    key = (action or "").strip()
    return ACTION_LABELS.get(key, key or "—")


@dataclass(frozen=True)
class AuditEventRow:
    """Display row for Utilities → Audit log."""

    uuid: str
    action: str
    action_label: str
    timestamp: datetime | None
    user: str
    user_uuid: str | None
    machine: str
    comment: str | None
    product_uuid: str | None
    product_name: str | None
    product_deleted: bool
    object_uuid: str | None
    object_filename: str | None
    object_filenames: tuple[str, ...]
    object_more_count: int
    summary: str
    details: dict[str, Any]


class ActivityService:
    def record(
        self,
        session: Session,
        action: ActivityAction | str,
        user: UserIdentity,
        product_id: int | None = None,
        object_id: int | None = None,
        details: dict[str, Any] | None = None,
        *,
        comment: str | None = None,
        product_uuid: str | None = None,
        product_name: str | None = None,
        object_uuid: str | None = None,
        object_filename: str | None = None,
    ) -> Activity:
        safe = redact_audit_details(details)
        note = (comment or "").strip() or None
        if note is None and safe:
            raw = safe.get("comment") or safe.get("reason")
            if isinstance(raw, str) and raw.strip():
                note = raw.strip()[:2000]

        snap_product_uuid = (product_uuid or "").strip() or None
        snap_product_name = (product_name or "").strip() or None
        snap_object_uuid = (object_uuid or "").strip() or None
        snap_object_filename = (object_filename or "").strip() or None

        if product_id is not None and (snap_product_uuid is None or snap_product_name is None):
            product = session.get(Product, product_id)
            if product is not None:
                snap_product_uuid = snap_product_uuid or product.uuid
                snap_product_name = snap_product_name or product.name
        if object_id is not None and (snap_object_uuid is None or snap_object_filename is None):
            obj = session.get(EngineeringObject, object_id)
            if obj is not None:
                snap_object_uuid = snap_object_uuid or obj.uuid
                snap_object_filename = snap_object_filename or (obj.filename or None)

        # Keep details searchable even after live FKs are nulled.
        if safe is None:
            safe = {}
        if snap_product_uuid and "product_uuid" not in safe:
            safe["product_uuid"] = snap_product_uuid
        if snap_product_name and "product_name" not in safe:
            safe["product_name"] = snap_product_name
        if snap_object_uuid and "object_uuid" not in safe:
            safe["object_uuid"] = snap_object_uuid
        if snap_object_filename and "filename" not in safe:
            safe["filename"] = snap_object_filename
        if not safe:
            safe = None

        activity = Activity(
            uuid=str(uuid.uuid4()),
            product_id=product_id,
            object_id=object_id,
            product_uuid=snap_product_uuid,
            product_name=snap_product_name,
            object_uuid=snap_object_uuid,
            object_filename=snap_object_filename,
            user=user.user_name,
            user_uuid=user.user_uuid,
            machine=user.machine_name,
            action=str(action),
            comment=note,
            details_json=json.dumps(safe) if safe else None,
        )
        session.add(activity)
        session.flush()
        return activity

    def detach_product_activities(self, session: Session, product_id: int) -> None:
        """Null live product/object FKs; keep snapshot columns and the rows."""
        from sqlalchemy import update

        object_ids = list(
            session.scalars(
                select(EngineeringObject.id).where(EngineeringObject.product_id == product_id)
            ).all()
        )
        if object_ids:
            session.execute(
                update(Activity)
                .where(Activity.object_id.in_(object_ids))
                .values(object_id=None)
            )
        session.execute(
            update(Activity).where(Activity.product_id == product_id).values(product_id=None)
        )
        session.flush()

    def detach_object_activities(self, session: Session, object_ids: list[int]) -> None:
        """Null live object FKs for purged objects; keep snapshot columns."""
        from sqlalchemy import update

        ids = [int(item) for item in object_ids if item]
        if not ids:
            return
        session.execute(
            update(Activity).where(Activity.object_id.in_(ids)).values(object_id=None)
        )
        session.flush()

    def record_or_merge_import_batch(
        self,
        session: Session,
        action: ActivityAction | str,
        user: UserIdentity,
        *,
        product_id: int,
        batch_id: str,
        filenames: list[str],
        count_delta: int,
        batch_total: int | None = None,
        git_commit: str | None = None,
        comment: str | None = None,
    ) -> Activity:
        """One Audit row per Add/Check-in batch across upload chunks.

        Chunks share ``batch_id`` (agent/browser). Filenames accumulate (capped);
        ``count`` sums successfully recorded files across chunks.
        """
        action_key = str(action)
        batch_key = (batch_id or "").strip()
        if not batch_key:
            raise ValueError("batch_id is required for import batch merge")
        names_in = [str(item).strip() for item in filenames if str(item).strip()]
        delta = max(0, int(count_delta))
        existing = self._find_import_batch_activity(
            session,
            product_id=product_id,
            user_name=user.user_name,
            action=action_key,
            batch_id=batch_key,
        )
        if existing is None:
            details: dict[str, Any] = {
                "batch_id": batch_key,
                "count": delta,
                "filenames": names_in[:200],
            }
            if names_in:
                details["filename"] = names_in[0]
            if batch_total is not None and int(batch_total) > 0:
                details["batch_total"] = int(batch_total)
            if git_commit:
                details["git_commit"] = str(git_commit)[:40]
            return self.record(
                session,
                action_key,
                user,
                product_id=product_id,
                object_id=None,
                details=details,
                comment=comment,
            )

        details = {}
        if existing.details_json:
            try:
                parsed = json.loads(existing.details_json)
                if isinstance(parsed, dict):
                    details = parsed
            except json.JSONDecodeError:
                details = {}
        prior = details.get("filenames")
        merged: list[str] = []
        seen: set[str] = set()
        if isinstance(prior, list):
            for item in prior:
                text = str(item).strip()
                if text and text not in seen:
                    seen.add(text)
                    merged.append(text)
        for text in names_in:
            if text not in seen:
                seen.add(text)
                merged.append(text)
        details["batch_id"] = batch_key
        details["filenames"] = merged[:200]
        if merged:
            details["filename"] = merged[0]
        prior_count = details.get("count")
        base = int(prior_count) if isinstance(prior_count, int) and prior_count > 0 else len(merged)
        # Prefer sum of chunk successes when prior count was tracking deltas.
        if isinstance(prior_count, int) and prior_count > 0:
            details["count"] = prior_count + delta
        else:
            details["count"] = max(base, len(merged))
        if batch_total is not None and int(batch_total) > 0:
            details["batch_total"] = int(batch_total)
        if git_commit:
            details["git_commit"] = str(git_commit)[:40]
        if comment and not (existing.comment or "").strip():
            existing.comment = comment.strip()[:2000]
        existing.details_json = json.dumps(redact_audit_details(details) or {})
        session.flush()
        return existing

    def _find_import_batch_activity(
        self,
        session: Session,
        *,
        product_id: int,
        user_name: str,
        action: str,
        batch_id: str,
    ) -> Activity | None:
        rows = list(
            session.scalars(
                select(Activity)
                .where(
                    Activity.product_id == product_id,
                    Activity.action == action,
                    Activity.user == user_name,
                )
                .order_by(Activity.timestamp.desc())
                .limit(40)
            ).all()
        )
        for row in rows:
            if not row.details_json:
                continue
            try:
                parsed = json.loads(row.details_json)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("batch_id") == batch_id:
                return row
        return None

    def list_events(
        self,
        session: Session,
        *,
        action: str | None = None,
        username: str | None = None,
        product_uuid: str | None = None,
        object_query: str | None = None,
        q: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = AUDIT_PAGE_SIZE,
    ) -> list[AuditEventRow]:
        """Newest-first audit rows for Utilities → Audit log."""
        take = max(1, min(int(limit or AUDIT_PAGE_SIZE), AUDIT_PAGE_SIZE))
        stmt = select(Activity).order_by(Activity.timestamp.desc(), Activity.id.desc())
        joined_product = False
        joined_object = False

        action_key = (action or "").strip()
        if action_key:
            action_keys = [part.strip() for part in action_key.split(",") if part.strip()]
            if len(action_keys) == 1:
                stmt = stmt.where(Activity.action == action_keys[0])
            elif action_keys:
                stmt = stmt.where(Activity.action.in_(action_keys))
        user_key = (username or "").strip()
        if user_key:
            stmt = stmt.where(Activity.user == user_key)
        if since is not None:
            stmt = stmt.where(Activity.timestamp >= since)
        if until is not None:
            stmt = stmt.where(Activity.timestamp <= until)

        product_key = (product_uuid or "").strip()
        if product_key:
            if not joined_product:
                stmt = stmt.outerjoin(Product, Activity.product_id == Product.id)
                joined_product = True
            stmt = stmt.where(
                or_(
                    Product.uuid == product_key,
                    Activity.product_uuid == product_key,
                )
            )

        obj_key = (object_query or "").strip()
        if obj_key:
            like = f"%{obj_key}%"
            if not joined_object:
                stmt = stmt.outerjoin(
                    EngineeringObject, Activity.object_id == EngineeringObject.id
                )
                joined_object = True
            stmt = stmt.where(
                or_(
                    EngineeringObject.uuid == obj_key,
                    EngineeringObject.filename.ilike(like),
                    Activity.object_uuid == obj_key,
                    Activity.object_filename.ilike(like),
                    Activity.details_json.ilike(like),
                )
            )

        search = (q or "").strip()
        if search:
            like = f"%{search}%"
            if not joined_product:
                stmt = stmt.outerjoin(Product, Activity.product_id == Product.id)
                joined_product = True
            if not joined_object:
                stmt = stmt.outerjoin(
                    EngineeringObject, Activity.object_id == EngineeringObject.id
                )
                joined_object = True
            stmt = stmt.where(
                or_(
                    Activity.user.ilike(like),
                    Activity.action.ilike(like),
                    Activity.comment.ilike(like),
                    Activity.details_json.ilike(like),
                    Activity.machine.ilike(like),
                    Activity.product_uuid.ilike(like),
                    Activity.product_name.ilike(like),
                    Activity.object_uuid.ilike(like),
                    Activity.object_filename.ilike(like),
                    Product.name.ilike(like),
                    Product.uuid.ilike(like),
                    EngineeringObject.filename.ilike(like),
                    EngineeringObject.uuid.ilike(like),
                )
            )

        stmt = stmt.limit(take)
        rows = list(session.scalars(stmt).unique().all())

        product_ids = {row.product_id for row in rows if row.product_id}
        object_ids = {row.object_id for row in rows if row.object_id}
        products: dict[int, Product] = {}
        objects: dict[int, EngineeringObject] = {}
        if product_ids:
            for product in session.scalars(
                select(Product).where(Product.id.in_(product_ids))
            ).all():
                products[product.id] = product
        if object_ids:
            for obj in session.scalars(
                select(EngineeringObject).where(EngineeringObject.id.in_(object_ids))
            ).all():
                objects[obj.id] = obj

        out: list[AuditEventRow] = []
        for row in rows:
            details: dict[str, Any] = {}
            if row.details_json:
                try:
                    parsed = json.loads(row.details_json)
                    if isinstance(parsed, dict):
                        details = parsed
                except json.JSONDecodeError:
                    details = {"raw": row.details_json}
            product = products.get(row.product_id) if row.product_id else None
            obj = objects.get(row.object_id) if row.object_id else None
            filename = _object_label(details, obj) or (row.object_filename or None)
            extra_names, more_count = _object_filename_list(details, obj)
            object_uuid = None
            if obj is not None:
                object_uuid = obj.uuid
            else:
                object_uuid = (row.object_uuid or "").strip() or None
                if object_uuid is None:
                    raw_uuid = details.get("object_uuid")
                    if isinstance(raw_uuid, str) and raw_uuid.strip():
                        object_uuid = raw_uuid.strip()
            product_uuid_out = product.uuid if product else ((row.product_uuid or "").strip() or None)
            product_name_out = product.name if product else ((row.product_name or "").strip() or None)
            if product_name_out is None:
                raw_name = details.get("product_name") or details.get("name")
                if isinstance(raw_name, str) and raw_name.strip():
                    product_name_out = raw_name.strip()
            if product_uuid_out is None:
                raw_pu = details.get("product_uuid")
                if isinstance(raw_pu, str) and raw_pu.strip():
                    product_uuid_out = raw_pu.strip()
            out.append(
                AuditEventRow(
                    uuid=row.uuid,
                    action=row.action,
                    action_label=action_label(row.action),
                    timestamp=row.timestamp,
                    user=row.user,
                    user_uuid=row.user_uuid,
                    machine=row.machine,
                    comment=row.comment,
                    product_uuid=product_uuid_out,
                    product_name=product_name_out,
                    product_deleted=bool(product_uuid_out) and product is None,
                    object_uuid=object_uuid,
                    object_filename=filename,
                    object_filenames=extra_names,
                    object_more_count=more_count,
                    summary=_event_summary(row.action, details, row.comment),
                    details=details,
                )
            )
        return out


def _object_filename_list(
    details: dict[str, Any], obj: EngineeringObject | None
) -> tuple[tuple[str, ...], int]:
    """Stored filenames for expand UI, plus how many more exist beyond the first."""
    names: list[str] = []
    raw = details.get("filenames")
    if isinstance(raw, list):
        names = [str(item).strip() for item in raw if str(item).strip()]
    if not names and obj is not None and (obj.filename or "").strip():
        names = [obj.filename.strip()]
    if not names:
        single = details.get("filename")
        if isinstance(single, str) and single.strip():
            names = [single.strip()]
    if len(names) <= 1:
        return tuple(names), 0
    count = details.get("count")
    total = int(count) if isinstance(count, int) and count > 0 else len(names)
    more = max(total - 1, len(names) - 1)
    return tuple(names), more


def _object_label(details: dict[str, Any], obj: EngineeringObject | None) -> str | None:
    if obj is not None and (obj.filename or "").strip():
        # Prefer batch list when present (force-undo / multi-remove keep one object_id).
        names = details.get("filenames")
        if isinstance(names, list) and len(names) > 1:
            pass
        else:
            return obj.filename
    names = details.get("filenames")
    if isinstance(names, list) and names:
        first = str(names[0])
        count = details.get("count")
        total = int(count) if isinstance(count, int) and count > 0 else len(names)
        extra = total - 1
        if extra > 0:
            return f"{first} (+{extra} more)"
        return first
    raw_name = details.get("filename")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    count = details.get("count")
    if isinstance(count, int) and count > 0:
        return f"{count} files"
    rel = details.get("relative_path")
    if isinstance(rel, str) and rel.strip():
        return rel.strip().rsplit("/", 1)[-1]
    return None


def _event_summary(
    action: str, details: dict[str, Any], comment: str | None
) -> str:
    parts: list[str] = []
    if comment:
        parts.append(comment)
    if action in {ActivityAction.PRODUCT_DELETED.value, "PRODUCT_DELETED"}:
        name = details.get("name") or details.get("product_name")
        if name:
            parts.append(str(name))
    if action in {ActivityAction.STATE_CHANGED.value, "STATE_CHANGED"}:
        old_s = details.get("old_state") or details.get("state_before")
        new_s = (
            details.get("new_state")
            or details.get("state")
            or details.get("state_after")
        )
        if old_s and new_s and old_s != new_s:
            parts.append(f"state {old_s} → {new_s}")
        old_ro = details.get("old_read_only")
        new_ro = details.get("read_only")
        if old_ro is not None and new_ro is not None and old_ro != new_ro:
            parts.append(f"read_only {old_ro} → {new_ro}")
    if action in {ActivityAction.PRODUCT_UPDATED.value, "PRODUCT_UPDATED"}:
        old_name = details.get("old_name")
        new_name = details.get("name")
        if old_name and new_name and old_name != new_name:
            parts.append(f"renamed {old_name} → {new_name}")
        changed = details.get("changed")
        if isinstance(changed, list) and changed and not parts:
            parts.append(", ".join(str(item) for item in changed[:6]))
    if action in {ActivityAction.CHECKED_IN.value, "CHECKED_IN"}:
        prev = details.get("previous_iteration")
        it = details.get("iteration")
        if prev is not None and it is not None:
            parts.append(f"iteration {prev} → {it}")
        elif it is not None:
            parts.append(f"iteration {it}")
        commit = details.get("git_commit")
        if commit:
            parts.append(f"git {str(commit)[:8]}")
    if action in {
        ActivityAction.OBJECT_ADDED.value,
        "OBJECT_ADDED",
        ActivityAction.OBJECT_REMOVED.value,
        "OBJECT_REMOVED",
        ActivityAction.CHECKED_OUT.value,
        "CHECKED_OUT",
    }:
        # Object column already shows the file label; keep summary for extras only.
        commit = details.get("git_commit")
        if commit and action in {ActivityAction.OBJECT_ADDED.value, "OBJECT_ADDED"}:
            parts.append(f"git {str(commit)[:8]}")
    if action in {
        ActivityAction.CHECKOUT_OVERRIDE.value,
        "CHECKOUT_OVERRIDE",
        ActivityAction.CHECKOUT_CANCELLED.value,
    }:
        prev = details.get("previous_user")
        if prev:
            parts.append(f"was {prev}")
    if action in {
        ActivityAction.USER_CREATED.value,
        ActivityAction.USER_DISABLED.value,
        ActivityAction.USER_ENABLED.value,
        ActivityAction.USER_LOGIN.value,
        ActivityAction.USER_LOGOUT.value,
        ActivityAction.LOGIN_FAILED.value,
        ActivityAction.ROLE_CHANGED.value,
        "ROLE_ASSIGNED",
        ActivityAction.MEMBERSHIP_CHANGED.value,
        ActivityAction.SYSTEM_SETTING_CHANGED.value,
    }:
        for key in (
            "username",
            "role",
            "setting",
            "target_user",
            "product",
            "reason",
            "ip",
        ):
            if details.get(key):
                parts.append(f"{key}={details[key]}")
                break
    return " · ".join(parts) if parts else ""


__all__ = [
    "ACTION_LABELS",
    "AUDIT_ACTION_FILTER_CHOICES",
    "AUDIT_PAGE_SIZE",
    "ActivityService",
    "AuditEventRow",
    "action_label",
    "redact_audit_details",
]
