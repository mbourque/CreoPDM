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


@dataclass(frozen=True)
class AuditEventRow:
    """Display row for Utilities → Audit log."""

    uuid: str
    action: str
    timestamp: datetime | None
    user: str
    user_uuid: str | None
    machine: str
    comment: str | None
    product_uuid: str | None
    product_name: str | None
    object_uuid: str | None
    object_filename: str | None
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
    ) -> Activity:
        safe = redact_audit_details(details)
        note = (comment or "").strip() or None
        if note is None and safe:
            raw = safe.get("comment") or safe.get("reason")
            if isinstance(raw, str) and raw.strip():
                note = raw.strip()[:2000]
        activity = Activity(
            uuid=str(uuid.uuid4()),
            product_id=product_id,
            object_id=object_id,
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

    def list_events(
        self,
        session: Session,
        *,
        action: str | None = None,
        username: str | None = None,
        product_uuid: str | None = None,
        object_query: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = AUDIT_PAGE_SIZE,
    ) -> list[AuditEventRow]:
        """Newest-first audit rows for Utilities → Audit log."""
        take = max(1, min(int(limit or AUDIT_PAGE_SIZE), AUDIT_PAGE_SIZE))
        stmt = select(Activity).order_by(Activity.timestamp.desc(), Activity.id.desc())

        action_key = (action or "").strip()
        if action_key:
            stmt = stmt.where(Activity.action == action_key)
        user_key = (username or "").strip()
        if user_key:
            stmt = stmt.where(Activity.user.ilike(f"%{user_key}%"))
        if since is not None:
            stmt = stmt.where(Activity.timestamp >= since)
        if until is not None:
            stmt = stmt.where(Activity.timestamp <= until)

        product_key = (product_uuid or "").strip()
        if product_key:
            stmt = stmt.join(Product, Activity.product_id == Product.id).where(
                Product.uuid == product_key
            )

        obj_key = (object_query or "").strip()
        if obj_key:
            # Match linked object uuid/filename, or filename stored only in details_json.
            like = f"%{obj_key}%"
            stmt = stmt.outerjoin(
                EngineeringObject, Activity.object_id == EngineeringObject.id
            ).where(
                or_(
                    EngineeringObject.uuid == obj_key,
                    EngineeringObject.filename.ilike(like),
                    Activity.details_json.ilike(like),
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
            filename = obj.filename if obj else None
            if not filename:
                raw_name = details.get("filename")
                filename = str(raw_name) if raw_name else None
            out.append(
                AuditEventRow(
                    uuid=row.uuid,
                    action=row.action,
                    timestamp=row.timestamp,
                    user=row.user,
                    user_uuid=row.user_uuid,
                    machine=row.machine,
                    comment=row.comment,
                    product_uuid=product.uuid if product else None,
                    product_name=product.name if product else None,
                    object_uuid=obj.uuid if obj else None,
                    object_filename=filename,
                    summary=_event_summary(row.action, details, row.comment),
                    details=details,
                )
            )
        return out


def _event_summary(
    action: str, details: dict[str, Any], comment: str | None
) -> str:
    parts: list[str] = []
    if comment:
        parts.append(comment)
    if action in {ActivityAction.PRODUCT_UPDATED.value, "PRODUCT_UPDATED"}:
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
        changed = details.get("changed")
        if isinstance(changed, list) and changed and not parts:
            parts.append(", ".join(str(item) for item in changed[:6]))
    if action in {ActivityAction.CHECKED_IN.value, "CHECKED_IN"}:
        it = details.get("iteration")
        if it is not None:
            parts.append(f"iteration {it}")
    if action in {
        "CHECKOUT_OVERRIDE",
        ActivityAction.CHECKOUT_CANCELLED.value,
    }:
        prev = details.get("previous_user")
        if prev:
            parts.append(f"was {prev}")
    if action in {
        "USER_CREATED",
        "USER_DISABLED",
        "USER_ENABLED",
        "ROLE_CHANGED",
        "ROLE_ASSIGNED",
        "MEMBERSHIP_CHANGED",
        "SYSTEM_SETTING_CHANGED",
    }:
        for key in ("username", "role", "setting", "target_user", "product"):
            if details.get(key):
                parts.append(f"{key}={details[key]}")
                break
    if not parts:
        filename = details.get("filename")
        if filename:
            parts.append(str(filename))
    return " · ".join(parts) if parts else ""


__all__ = [
    "AUDIT_PAGE_SIZE",
    "ActivityService",
    "AuditEventRow",
    "redact_audit_details",
]
