"""The in-app inbox behind the toast and the bell.

A row is created for each person a comment event concerns. Rows are always filtered through the
product audience when listed, so someone who loses access to a product stops seeing (and being
counted for) its notifications immediately.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from creopdm.models.comment import UserNotification
from creopdm.models.product import Product
from creopdm.models.user import User, UserProduct

MAX_LIST = 50


def _visible_filter(user: User):
    """SQL condition: notifications of products the user may still use."""
    if getattr(user, "access_all_products", True):
        return None
    member = select(UserProduct.product_id).where(UserProduct.user_id == user.id)
    return UserNotification.product_id.in_(member)


class UserNotificationService:
    def create(
        self,
        db: Session,
        *,
        user: User,
        kind: str,
        product: Product,
        target_type: str,
        target_uuid: str,
        title: str,
        excerpt: str,
        actor: str,
        comment_id: int | None,
    ) -> UserNotification:
        row = UserNotification(
            user_id=user.id,
            kind=kind,
            comment_id=comment_id,
            product_id=product.id,
            target_type=target_type,
            target_uuid=target_uuid,
            title=title[:255],
            excerpt=excerpt[:300],
            actor=actor,
        )
        db.add(row)
        db.flush()
        return row

    def _base(self, user: User):
        stmt = select(UserNotification).where(UserNotification.user_id == user.id)
        cond = _visible_filter(user)
        if cond is not None:
            stmt = stmt.where(cond)
        return stmt

    def list_for_user(
        self, db: Session, user: User, *, after: int = 0, limit: int = 20
    ) -> list[UserNotification]:
        stmt = self._base(user)
        if after > 0:
            stmt = stmt.where(UserNotification.id > after).order_by(UserNotification.id.asc())
        else:
            stmt = stmt.order_by(UserNotification.id.desc())
        return list(db.scalars(stmt.limit(max(1, min(limit, MAX_LIST)))).all())

    def unread_count(self, db: Session, user: User) -> int:
        sub = self._base(user).where(UserNotification.read_at.is_(None)).subquery()
        return int(db.scalar(select(func.count()).select_from(sub)) or 0)

    def latest_id(self, db: Session, user: User) -> int:
        stmt = select(func.max(UserNotification.id)).where(UserNotification.user_id == user.id)
        return int(db.scalar(stmt) or 0)

    def mark_seen(self, db: Session, user: User, ids: list[int]) -> None:
        if not ids:
            return
        db.execute(
            update(UserNotification)
            .where(UserNotification.user_id == user.id)
            .where(UserNotification.id.in_(ids))
            .where(UserNotification.seen_at.is_(None))
            .values(seen_at=datetime.now(timezone.utc))
        )

    def mark_read(self, db: Session, user: User, ids: list[int] | None) -> None:
        """``ids`` None marks everything read."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(UserNotification)
            .where(UserNotification.user_id == user.id)
            .where(UserNotification.read_at.is_(None))
        )
        if ids is not None:
            stmt = stmt.where(UserNotification.id.in_(ids))
        db.execute(stmt.values(read_at=now, seen_at=func.coalesce(UserNotification.seen_at, now)))

    def clear_for_user(self, db: Session, user: User) -> None:
        """The bell's Clear: remove this person's notifications (nobody else's, no audit rows)."""
        db.execute(delete(UserNotification).where(UserNotification.user_id == user.id))

    def delete_for_product(self, db: Session, product_id: int) -> None:
        db.execute(delete(UserNotification).where(UserNotification.product_id == product_id))
