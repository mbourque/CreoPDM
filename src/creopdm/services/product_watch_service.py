"""Product watch / email subscribe for activity notifications."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.product import Product
from creopdm.models.user import ProductWatch, User
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.utils.timefmt import format_local

logger = get_logger("product_watch")

_MAX_FILES_IN_EMAIL = 40


def _usable_watch_email(raw: str | None) -> str | None:
    """Return a stripped address if it looks like name@domain.tld; else None.

    Intentionally does not import email-validator — watch/notify must work when
    that optional-at-runtime dep is missing from a deployed venv.
    """
    email = str(raw or "").strip()
    at = email.rfind("@")
    domain = email[at + 1 :] if at >= 0 else ""
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if (
        not email
        or at < 1
        or "." not in domain
        or not tld.isalpha()
        or len(tld) < 2
    ):
        return None
    return email


class ProductWatchService:
    def __init__(self, notifications: NotificationService) -> None:
        self._notifications = notifications

    def email_notifications_enabled(self, *, email_enabled: bool) -> bool:
        return bool(email_enabled)

    def watch_eligibility(
        self,
        user: User | None,
        *,
        email_enabled: bool,
    ) -> tuple[bool, str | None]:
        """Return (can_watch, reason). Notifications off is handled by hiding the UI.

        Uses a light email presence check only — full email-validator runs on
        account create/edit. Pages must not fail closed when that package is
        missing from the server venv after a deploy.
        """
        if not email_enabled:
            return False, "Email notifications are disabled."
        if user is None:
            return False, "Sign in to watch a product."
        try:
            email = _usable_watch_email(getattr(user, "email", None))
        except Exception:
            logger.exception("watch_eligibility could not read user email")
            return False, "Product watch is temporarily unavailable."
        if email is None:
            return (
                False,
                "Set a valid email address on your account before watching a product.",
            )
        return True, None

    def is_watching(self, db: Session, user_id: int, product_id: int) -> bool:
        try:
            row = db.scalar(
                select(ProductWatch).where(
                    ProductWatch.user_id == user_id,
                    ProductWatch.product_id == product_id,
                )
            )
            return row is not None
        except Exception:
            # Missing product_watches table (migration not applied) must not 500 pages.
            logger.exception("is_watching failed user_id=%s product_id=%s", user_id, product_id)
            return False

    def subscribe(self, db: Session, user: User, product: Product, *, email_enabled: bool) -> None:
        can, reason = self.watch_eligibility(user, email_enabled=email_enabled)
        if not can:
            raise ValidationAppError(reason or "Cannot watch this product.")
        if self.is_watching(db, user.id, product.id):
            return
        db.add(ProductWatch(user_id=user.id, product_id=product.id))
        db.flush()
        logger.info(
            "product_watch subscribe user_id=%s product_id=%s product=%s",
            user.id,
            product.id,
            product.uuid,
        )

    def unsubscribe(self, db: Session, user: User, product: Product) -> None:
        db.execute(
            delete(ProductWatch).where(
                ProductWatch.user_id == user.id,
                ProductWatch.product_id == product.id,
            )
        )
        db.flush()
        logger.info(
            "product_watch unsubscribe user_id=%s product_id=%s product=%s",
            user.id,
            product.id,
            product.uuid,
        )

    def list_watcher_emails(
        self,
        db: Session,
        product_id: int,
        *,
        exclude_user_id: int | None = None,
    ) -> list[str]:
        stmt = (
            select(User.email, User.id)
            .join(ProductWatch, ProductWatch.user_id == User.id)
            .where(ProductWatch.product_id == product_id)
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        out: list[str] = []
        for email, _uid in db.execute(stmt).all():
            usable = _usable_watch_email(email)
            if usable is not None:
                out.append(usable)
        # Stable unique order
        seen: set[str] = set()
        unique: list[str] = []
        for addr in out:
            key = addr.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(addr)
        return unique

    def notify_product_activity(
        self,
        db: Session,
        *,
        product: Product,
        action: str,
        actor: User | None,
        actor_label: str,
        filenames: list[str],
        base_url: str,
        object_uuid: str | None = None,
        email_enabled: bool,
    ) -> None:
        if not email_enabled:
            logger.info(
                "product_activity skip product=%s action=%s: email notifications disabled",
                product.uuid,
                action,
            )
            return
        exclude_id = actor.id if actor is not None else None
        recipients = self.list_watcher_emails(db, product.id, exclude_user_id=exclude_id)
        if not recipients:
            logger.info(
                "product_activity skip product=%s action=%s actor_id=%s: no watcher recipients",
                product.uuid,
                action,
                exclude_id,
            )
            return

        files = [f for f in filenames if (f or "").strip()]
        # Same local clock as Files / Details (server TZ via format_local), not bare UTC.
        when = format_local(datetime.now(timezone.utc))
        base = (base_url or "").rstrip("/")
        if object_uuid and len(files) == 1:
            link = f"{base}/products/{product.uuid}/objects/{object_uuid}"
        else:
            link = f"{base}/?product={product.uuid}"

        if not files:
            files_block = "(product settings)"
        elif len(files) == 1:
            files_block = files[0]
        else:
            shown = files[:_MAX_FILES_IN_EMAIL]
            extra = len(files) - len(shown)
            lines = "\n".join(f"  - {name}" for name in shown)
            if extra > 0:
                lines += f"\n  … and {extra} more"
            files_block = f"{len(files)} files:\n{lines}"

        subject = f"CreoPDM: {action} in {product.name}"
        message = (
            f"Product: {product.name}\n"
            f"Action: {action}\n"
            f"By: {actor_label}\n"
            f"When: {when}\n"
            f"Files: {files_block}\n"
            f"\nOpen: {link}\n"
        )
        logger.info(
            "product_activity notify product=%s action=%s recipients=%s files=%s",
            product.uuid,
            action,
            recipients,
            files[:5],
        )
        self._notifications.notify(
            NotificationEvent.PRODUCT_ACTIVITY,
            subject=subject,
            message=message,
            to=recipients,
        )
