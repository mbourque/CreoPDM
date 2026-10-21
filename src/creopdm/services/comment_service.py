"""Comments: threads on a product, a file, an exact version, a baseline or a baseline's file.

Who may take part is decided by the product audience (``UserService.product_audience``): readers,
writers, @mention candidates and notification recipients all come from it. Every event is written
to the audit log, and the people it concerns get an in-app notification (toast + bell); e-mail is
only an extra and only when e-mail is set up.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote
import uuid as uuid_lib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from creopdm.constants import ActivityAction
from creopdm.exceptions import NotFoundError, PermissionDeniedError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.baseline import Baseline, BaselineMember
from creopdm.models.comment import (
    NOTIFY_MENTION,
    NOTIFY_ON_MINE,
    NOTIFY_REOPENED,
    NOTIFY_REPLY,
    NOTIFY_RESOLVED,
    TARGET_BASELINE,
    TARGET_BASELINE_MEMBER,
    TARGET_OBJECT,
    TARGET_PRODUCT,
    TARGET_TYPES,
    TARGET_VERSION,
    Comment,
    CommentAttachment,
    CommentMention,
    UserNotification,
)
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.auth_constants import PERMISSION_COMMENTS_VIEW
from creopdm.models.user import Permission, RolePermission, User, UserRole
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.services.product_watch_service import _usable_watch_email
from creopdm.services.user_notification_service import UserNotificationService
from creopdm.services.user_service import UserService
from creopdm.utils.comment_images import (
    MAX_IMAGES_PER_COMMENT,
    CommentImageError,
    process_image,
)
from creopdm.utils.identity import UserIdentity
from creopdm.utils.timefmt import as_utc

logger = get_logger(__name__)

MAX_BODY = 4000
MAX_NOTE = 500
EXCERPT = 200
DRAFT_TTL = timedelta(hours=24)
_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,64})")
FILTERS = {"open", "resolved", "mine", "mentions", "all"}


@dataclass
class Actor:
    """Who is acting. ``user`` is None when sign-in is off (a local single-user setup)."""

    user: User | None
    username: str
    display_name: str
    can_resolve_any: bool = False
    can_admin: bool = False

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user is not None else None


@dataclass
class _Target:
    name: str
    target_uuid: str
    version_id: int | None = None
    version_display: str = ""
    object_id: int | None = None
    owner_username: str = ""


def _version_display(revision: str | None, iteration: int | None) -> str:
    if not revision:
        return ""
    return f"{revision}.{iteration}" if iteration is not None else str(revision)


def _iso(value: datetime | None) -> str | None:
    utc = as_utc(value)
    return utc.isoformat() if utc is not None else None


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT else flat[: EXCERPT - 1] + "…"


class CommentService:
    def __init__(
        self,
        activities: ActivityService,
        accounts: UserService,
        inbox: UserNotificationService,
        notifications: NotificationService,
        email_enabled=lambda: False,
    ) -> None:
        self._activities = activities
        self._accounts = accounts
        self._inbox = inbox
        self._notifications = notifications
        self._email_enabled = email_enabled

    # ------------------------------------------------------------------ targets
    def _target(self, db: Session, product: Product, target_type: str, target_uuid: str) -> _Target:
        if target_type not in TARGET_TYPES:
            raise ValidationAppError("Unknown comment target.")
        key = (target_uuid or "").strip()
        if target_type == TARGET_PRODUCT:
            if key != product.uuid:
                raise NotFoundError("Product not found.")
            return _Target(product.name, product.uuid)
        if target_type == TARGET_OBJECT:
            obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == key))
            if obj is None or obj.product_id != product.id:
                raise NotFoundError("File not found.")
            current = obj.current_version
            return _Target(
                obj.filename,
                obj.uuid,
                version_id=obj.current_version_id,
                version_display=_version_display(
                    getattr(current, "revision", obj.revision),
                    getattr(current, "iteration", obj.iteration),
                ),
                object_id=obj.id,
                owner_username=str(getattr(obj, "created_by", "") or ""),
            )
        if target_type == TARGET_VERSION:
            ver = db.scalar(select(ObjectVersion).where(ObjectVersion.uuid == key))
            obj = db.get(EngineeringObject, ver.object_id) if ver is not None else None
            if ver is None or obj is None or obj.product_id != product.id:
                raise NotFoundError("Version not found.")
            return _Target(
                obj.filename,
                ver.uuid,
                version_id=ver.id,
                version_display=_version_display(ver.revision, ver.iteration),
                object_id=obj.id,
            )
        base_uuid, _, object_uuid = key.partition("/")
        baseline = db.scalar(select(Baseline).where(Baseline.uuid == base_uuid))
        if baseline is None or baseline.product_id != product.id:
            raise NotFoundError("Baseline not found.")
        if target_type == TARGET_BASELINE:
            if object_uuid:
                raise NotFoundError("Baseline not found.")
            return _Target(
                baseline.name, baseline.uuid, owner_username=str(baseline.created_by or "")
            )
        obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == object_uuid))
        member = (
            db.scalar(
                select(BaselineMember)
                .where(BaselineMember.baseline_id == baseline.id)
                .where(BaselineMember.object_id == obj.id)
            )
            if obj is not None
            else None
        )
        if member is None:
            raise NotFoundError("That file is not part of the baseline.")
        return _Target(
            f"{member.filename} (in {baseline.name})",
            key,
            version_id=member.object_version_id,
            version_display=_version_display(member.revision, member.iteration),
            object_id=member.object_id,
        )

    def _names(self, db: Session, rows: list[Comment]) -> dict[tuple[str, str], str]:
        """Display names for the targets of many comments, in a few queries."""
        names: dict[tuple[str, str], str] = {}
        objects = {c.target_uuid for c in rows if c.target_type == TARGET_OBJECT}
        versions = {c.target_uuid for c in rows if c.target_type == TARGET_VERSION}
        baselines = {c.target_uuid for c in rows if c.target_type == TARGET_BASELINE}
        members = {c.target_uuid for c in rows if c.target_type == TARGET_BASELINE_MEMBER}
        products = {c.product_id for c in rows if c.target_type == TARGET_PRODUCT}
        if objects:
            for o in db.scalars(select(EngineeringObject).where(EngineeringObject.uuid.in_(objects))):
                names[(TARGET_OBJECT, o.uuid)] = o.filename
        if versions:
            for v, o in db.execute(
                select(ObjectVersion, EngineeringObject)
                .join(EngineeringObject, EngineeringObject.id == ObjectVersion.object_id)
                .where(ObjectVersion.uuid.in_(versions))
            ):
                names[(TARGET_VERSION, v.uuid)] = o.filename
        wanted = baselines | {m.partition("/")[0] for m in members}
        by_uuid: dict[str, str] = {}
        if wanted:
            by_uuid = {
                b.uuid: b.name for b in db.scalars(select(Baseline).where(Baseline.uuid.in_(wanted)))
            }
        for b in baselines:
            names[(TARGET_BASELINE, b)] = by_uuid.get(b, "baseline")
        if members:
            object_uuids = {m.partition("/")[2] for m in members}
            files = {
                o.uuid: o.filename
                for o in db.scalars(
                    select(EngineeringObject).where(EngineeringObject.uuid.in_(object_uuids))
                )
            }
            for m in members:
                b, _, o = m.partition("/")
                names[(TARGET_BASELINE_MEMBER, m)] = (
                    f"{files.get(o, 'file')} (in {by_uuid.get(b, 'baseline')})"
                )
        if products:
            for p in db.scalars(select(Product).where(Product.id.in_(products))):
                names[(TARGET_PRODUCT, p.uuid)] = p.name
        return names

    # ------------------------------------------------------------------ mentions
    def _commenter_ids(self, db: Session) -> set[int]:
        """Users whose role has comments.view: the only people who can be tagged or notified.
        Someone whose role lacks it cannot see comments, so tagging them would tell them nothing."""
        return set(
            db.scalars(
                select(UserRole.user_id)
                .join(RolePermission, RolePermission.role_id == UserRole.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(Permission.key == PERMISSION_COMMENTS_VIEW)
            )
        )

    def mentionable(
        self,
        db: Session,
        product: Product,
        query: str = "",
        limit: int = 30,
        exclude_user_id: int | None = None,
    ) -> list[dict]:
        """People the author can @mention: the product's audience who may view comments, never the author."""
        needle = (query or "").strip().lower().lstrip("@")
        out: list[dict] = []
        allowed = self._commenter_ids(db)
        for user in self._accounts.product_audience(db, product):
            if (exclude_user_id is not None and user.id == exclude_user_id) or user.id not in allowed:
                continue
            username = str(user.username or "")
            display = str(user.display_name or "")
            if needle and needle not in username.lower() and needle not in display.lower():
                continue
            out.append({"username": username, "display_name": display or username})
            if len(out) >= limit:
                break
        return out

    def _parse_mentions(
        self, db: Session, product: Product, body: str, actor: Actor
    ) -> tuple[list[User], list[str]]:
        """(users to record, names that matched nobody in the audience)."""
        allowed = self._commenter_ids(db)
        audience = {
            str(u.username).lower(): u
            for u in self._accounts.product_audience(db, product)
            if u.id in allowed
        }
        found: list[User] = []
        ignored: list[str] = []
        seen: set[str] = set()
        for name in _MENTION_RE.findall(body):
            low = name.lower()
            if low in seen:
                continue
            seen.add(low)
            user = audience.get(low)
            if user is None:
                ignored.append(name)
            elif actor.user is not None and user.id == actor.user.id:
                continue  # mentioning yourself tells nobody
            else:
                found.append(user)
        return found, ignored

    # ------------------------------------------------------------------ attachments
    def upload_attachment(
        self, db: Session, product: Product, actor: Actor, filename: str, raw: bytes
    ) -> CommentAttachment:
        self.purge_stale_drafts(db)
        try:
            processed = process_image(raw)
        except CommentImageError as exc:
            raise ValidationAppError(str(exc)) from exc
        label = re.sub(r"[\\/\x00-\x1f]", "_", (filename or "").strip())[:200] or "image"
        row = CommentAttachment(
            uuid=str(uuid_lib.uuid4()),
            product_id=product.id,
            comment_id=None,
            filename=label,
            content_type=processed.content_type,
            size=len(processed.data),
            width=processed.width,
            height=processed.height,
            sha256=processed.sha256,
            data=processed.data,
            thumb=processed.thumb,
            created_by=actor.username,
        )
        db.add(row)
        db.flush()
        return row

    def get_attachment(self, db: Session, attachment_uuid: str) -> CommentAttachment:
        row = db.scalar(
            select(CommentAttachment)
            .where(CommentAttachment.uuid == attachment_uuid)
            .where(CommentAttachment.deleted_at.is_(None))
        )
        if row is None:
            raise NotFoundError("Image not found.")
        return row

    def purge_stale_drafts(self, db: Session) -> None:
        cutoff = datetime.now(timezone.utc) - DRAFT_TTL
        db.execute(
            delete(CommentAttachment)
            .where(CommentAttachment.comment_id.is_(None))
            .where(CommentAttachment.created_at < cutoff)
        )

    def _link_attachments(
        self, db: Session, product: Product, actor: Actor, comment: Comment, uuids: list[str]
    ) -> None:
        wanted = [u for u in dict.fromkeys(uuids or []) if u]
        if not wanted:
            return
        existing = self._attachments(db, [comment.id]).get(comment.id, [])
        if len(existing) + len(wanted) > MAX_IMAGES_PER_COMMENT:
            raise ValidationAppError(f"A comment can have at most {MAX_IMAGES_PER_COMMENT} images.")
        rows = list(
            db.scalars(
                select(CommentAttachment)
                .where(CommentAttachment.uuid.in_(wanted))
                .where(CommentAttachment.comment_id.is_(None))
                .where(CommentAttachment.product_id == product.id)
                .where(CommentAttachment.created_by == actor.username)
            )
        )
        if len(rows) != len(wanted):
            raise ValidationAppError("An attached image is no longer available. Add it again.")
        for row in rows:
            row.comment_id = comment.id

    def _attachments(self, db: Session, comment_ids: list[int]) -> dict[int, list[CommentAttachment]]:
        out: dict[int, list[CommentAttachment]] = {}
        if not comment_ids:
            return out
        stmt = (
            select(CommentAttachment)
            .where(CommentAttachment.comment_id.in_(comment_ids))
            .where(CommentAttachment.deleted_at.is_(None))
            .order_by(CommentAttachment.id)
        )
        for row in db.scalars(stmt):
            out.setdefault(int(row.comment_id), []).append(row)
        return out

    # ------------------------------------------------------------------ write
    def _body(self, body: str, has_images: bool) -> str:
        text = (body or "").strip()
        if not text and not has_images:
            raise ValidationAppError("Write something first.")
        if len(text) > MAX_BODY:
            raise ValidationAppError(f"A comment can be at most {MAX_BODY} characters.")
        return text

    def _audit(
        self,
        db: Session,
        action: ActivityAction,
        identity: UserIdentity,
        product: Product,
        comment: Comment,
        *,
        target_name: str,
        version_display: str,
        mentions: list[str],
        images: int,
        object_id: int | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "comment_uuid": comment.uuid,
            "thread_uuid": self._thread_uuid(db, comment),
            "target_type": comment.target_type,
            "target_uuid": comment.target_uuid,
            "target_name": target_name,
            "version_display": version_display,
            "excerpt": _excerpt(comment.body),
            "mentions": mentions,
            "image_count": images,
        }
        details.update(extra or {})
        self._activities.record(
            db, action, identity, product_id=product.id, object_id=object_id, details=details
        )

    def _thread_uuid(self, db: Session, comment: Comment) -> str:
        if comment.parent_id is None:
            return comment.uuid
        root = db.get(Comment, comment.parent_id)
        return root.uuid if root is not None else comment.uuid

    def create(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        identity: UserIdentity,
        *,
        target_type: str,
        target_uuid: str,
        body: str,
        parent_uuid: str | None = None,
        attachment_uuids: list[str] | None = None,
        anchor: dict | None = None,
        base_url: str = "",
    ) -> dict[str, Any]:
        parent: Comment | None = None
        if parent_uuid:
            parent = self._get(db, parent_uuid)
            if parent.product_id != product.id or parent.parent_id is not None:
                raise NotFoundError("Comment not found.")
            if parent.deleted_at is not None:
                raise ValidationAppError("That comment was deleted.")
            target_type, target_uuid = parent.target_type, parent.target_uuid
        target = self._target(db, product, target_type, target_uuid)
        text = self._body(body, bool(attachment_uuids))
        comment = Comment(
            uuid=str(uuid_lib.uuid4()),
            product_id=product.id,
            target_type=target_type,
            target_uuid=target.target_uuid,
            version_id=parent.version_id if parent is not None else target.version_id,
            anchor_json=json.dumps(anchor) if anchor else None,
            parent_id=parent.id if parent is not None else None,
            body=text,
            author=actor.username,
            author_user_id=actor.user_id,
        )
        db.add(comment)
        db.flush()
        self._link_attachments(db, product, actor, comment, list(attachment_uuids or []))
        mentioned, ignored = self._parse_mentions(db, product, text, actor)
        for user in mentioned:
            db.add(CommentMention(comment_id=comment.id, user_id=user.id))
        db.flush()
        images = len(self._attachments(db, [comment.id]).get(comment.id, []))
        names = [str(u.username) for u in mentioned]
        self._audit(
            db,
            ActivityAction.COMMENT_ADDED,
            identity,
            product,
            comment,
            target_name=target.name,
            version_display=target.version_display,
            mentions=names,
            images=images,
            object_id=target.object_id,
        )
        self._tell_new(db, product, actor, comment, parent, target, mentioned, images, base_url)
        out = self.serialize(db, [comment], actor)[0]
        out["not_notified"] = ignored
        return out

    def _recipients(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        comment: Comment,
        parent: Comment | None,
        target: _Target,
        mentioned: list[User],
    ) -> dict[int, tuple[User, str]]:
        """user id -> (user, kind). Strongest reason wins; never the actor; audience only."""
        audience = {u.id: u for u in self._accounts.product_audience(db, product)}
        by_name = {str(u.username).lower(): u for u in audience.values()}
        chosen: dict[int, tuple[User, str]] = {}

        def add(user: User | None, kind: str) -> None:
            if user is None or user.id not in audience:
                return
            if actor.user is not None and user.id == actor.user.id:
                return
            chosen.setdefault(user.id, (user, kind))

        for user in mentioned:
            add(user, NOTIFY_MENTION)
        if parent is not None:
            add(audience.get(parent.author_user_id or -1), NOTIFY_REPLY)
        elif target.owner_username:
            add(by_name.get(target.owner_username.lower()), NOTIFY_ON_MINE)
        return chosen

    def _deep_link(
        self, db: Session, base_url: str, product: Product, comment: Comment, target: _Target
    ) -> str:
        """The exact place the thread is shown: the same links the toast and the bell use."""
        base = (base_url or "").rstrip("/")
        if not base:
            return ""
        p = quote(product.uuid, safe="")
        thread = comment.uuid
        if comment.parent_id:
            thread = db.scalar(select(Comment.uuid).where(Comment.id == comment.parent_id)) or thread
        t = f"&thread={quote(thread, safe='')}"
        kind = comment.target_type
        if kind == TARGET_OBJECT:
            return f"{base}/products/{p}/objects/{quote(comment.target_uuid, safe='')}?tab=discussion{t}"
        version_uuid = ""
        if comment.version_id:
            version_uuid = db.scalar(select(ObjectVersion.uuid).where(ObjectVersion.id == comment.version_id)) or ""
        if kind == TARGET_VERSION:
            obj_uuid = (
                db.scalar(select(EngineeringObject.uuid).where(EngineeringObject.id == target.object_id))
                if target.object_id
                else None
            )
            if obj_uuid:
                return (
                    f"{base}/products/{p}/objects/{quote(obj_uuid, safe='')}"
                    f"/versions/{quote(comment.target_uuid, safe='')}?tab=discussion{t}"
                )
        if kind == TARGET_BASELINE:
            return f"{base}/?product={p}&tab=baselines&baseline={quote(comment.target_uuid, safe='')}&discussion=1{t}"
        if kind == TARGET_BASELINE_MEMBER and version_uuid:
            baseline_uuid, _, obj_uuid = comment.target_uuid.partition("/")
            return (
                f"{base}/products/{p}/objects/{quote(obj_uuid, safe='')}/versions/{quote(version_uuid, safe='')}"
                f"?baseline={quote(baseline_uuid, safe='')}&tab=discussion{t}"
            )
        return f"{base}/?product={p}&tab=discussion{t}"

    def _tell_new(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        comment: Comment,
        parent: Comment | None,
        target: _Target,
        mentioned: list[User],
        images: int,
        base_url: str,
    ) -> None:
        recipients = self._recipients(db, product, actor, comment, parent, target, mentioned)
        for user, kind in recipients.values():
            self._deliver(
                db,
                user=user,
                kind=kind,
                product=product,
                comment=comment,
                target=target,
                actor=actor,
                images=images,
                base_url=base_url,
            )

    def _deliver(
        self,
        db: Session,
        *,
        user: User,
        kind: str,
        product: Product,
        comment: Comment,
        target: _Target,
        actor: Actor,
        images: int,
        base_url: str,
        note: str = "",
    ) -> None:
        if user.id not in self._commenter_ids(db):
            return  # a role without comments.view cannot see comments, so it is told nothing
        who = actor.display_name or actor.username
        verb = {
            NOTIFY_MENTION: "mentioned you on",
            NOTIFY_REPLY: "replied to you on",
            NOTIFY_ON_MINE: "commented on",
            NOTIFY_RESOLVED: "resolved your comment on",
            NOTIFY_REOPENED: "reopened your resolved comment on",
        }[kind]
        title = f"{who} {verb} {target.name}"
        excerpt = _excerpt(note or comment.body) + (" (with image)" if images else "")
        self._inbox.create(
            db,
            user=user,
            kind=kind,
            product=product,
            target_type=comment.target_type,
            target_uuid=comment.target_uuid,
            title=title,
            excerpt=excerpt,
            actor=actor.username,
            comment_id=comment.id,
        )
        if not self._email_enabled():
            return
        address = _usable_watch_email(user.email)
        if not address:
            return
        link = self._deep_link(db, base_url, product, comment, target)
        try:
            self._notifications.notify(
                NotificationEvent.COMMENT_MENTION,
                subject=f"CreoPDM: {title}",
                message=f"{title} in {product.name}:\n\n{excerpt}\n\n{link}",
                to=address,
            )
        except Exception as exc:  # noqa: BLE001 — a mail problem never blocks a comment
            logger.warning("Comment e-mail to user %s failed: %s", user.id, exc)

    def edit(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        identity: UserIdentity,
        comment_uuid: str,
        *,
        body: str,
        add_attachment_uuids: list[str] | None = None,
        remove_attachment_uuids: list[str] | None = None,
        base_url: str = "",
    ) -> dict[str, Any]:
        comment = self._get(db, comment_uuid)
        if comment.product_id != product.id or comment.deleted_at is not None:
            raise NotFoundError("Comment not found.")
        if not self._is_author(actor, comment):
            raise PermissionDeniedError("You can only edit your own comments.")
        removing = [u for u in (remove_attachment_uuids or []) if u]
        if removing:
            db.execute(
                delete(CommentAttachment)
                .where(CommentAttachment.comment_id == comment.id)
                .where(CommentAttachment.uuid.in_(removing))
            )
        self._link_attachments(db, product, actor, comment, list(add_attachment_uuids or []))
        images = len(self._attachments(db, [comment.id]).get(comment.id, []))
        text = self._body(body, images > 0)
        comment.body = text
        comment.edited_at = datetime.now(timezone.utc)
        previous = {
            m.user_id for m in db.scalars(select(CommentMention).where(CommentMention.comment_id == comment.id))
        }
        mentioned, ignored = self._parse_mentions(db, product, text, actor)
        db.execute(delete(CommentMention).where(CommentMention.comment_id == comment.id))
        for user in mentioned:
            db.add(CommentMention(comment_id=comment.id, user_id=user.id))
        db.flush()
        target = self._target(db, product, comment.target_type, comment.target_uuid)
        self._audit(
            db,
            ActivityAction.COMMENT_EDITED,
            identity,
            product,
            comment,
            target_name=target.name,
            version_display=target.version_display,
            mentions=[str(u.username) for u in mentioned],
            images=images,
            object_id=target.object_id,
        )
        # Only people newly mentioned by the edit are told.
        fresh = [u for u in mentioned if u.id not in previous]
        if fresh:
            audience = {u.id for u in self._accounts.product_audience(db, product)}
            for user in fresh:
                if user.id in audience:
                    self._deliver(
                        db,
                        user=user,
                        kind=NOTIFY_MENTION,
                        product=product,
                        comment=comment,
                        target=target,
                        actor=actor,
                        images=images,
                        base_url=base_url,
                    )
        out = self.serialize(db, [comment], actor)[0]
        out["not_notified"] = ignored
        return out

    def delete(
        self, db: Session, product: Product, actor: Actor, identity: UserIdentity, comment_uuid: str
    ) -> None:
        comment = self._get(db, comment_uuid)
        if comment.product_id != product.id or comment.deleted_at is not None:
            raise NotFoundError("Comment not found.")
        own = self._is_author(actor, comment)
        if not own and not actor.can_admin:
            raise PermissionDeniedError("You can only delete your own comments.")
        target = self._target(db, product, comment.target_type, comment.target_uuid)
        images = len(self._attachments(db, [comment.id]).get(comment.id, []))
        self._audit(
            db,
            ActivityAction.COMMENT_DELETED,
            identity,
            product,
            comment,
            target_name=target.name,
            version_display=target.version_display,
            mentions=[],
            images=images,
            object_id=target.object_id,
            extra={"comment_author": comment.author},
        )
        db.execute(delete(CommentAttachment).where(CommentAttachment.comment_id == comment.id))
        db.execute(delete(CommentMention).where(CommentMention.comment_id == comment.id))
        comment.body = ""
        comment.deleted_at = datetime.now(timezone.utc)
        db.flush()

    def resolve(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        identity: UserIdentity,
        comment_uuid: str,
        *,
        note: str = "",
        base_url: str = "",
    ) -> dict[str, Any]:
        root = self._thread_root(db, product, comment_uuid)
        if root.resolved_at is not None:
            return self.serialize(db, [root], actor)[0]
        self._require_may_resolve(db, actor, root)
        target = self._target(db, product, root.target_type, root.target_uuid)
        clean = (note or "").strip()[:MAX_NOTE]
        root.resolved_by = actor.username
        root.resolved_at = datetime.now(timezone.utc)
        root.resolution_note = clean or None
        root.resolved_in_version_id = target.version_id if target.object_id else None
        db.flush()
        self._audit(
            db,
            ActivityAction.COMMENT_RESOLVED,
            identity,
            product,
            root,
            target_name=target.name,
            version_display=target.version_display,
            mentions=[],
            images=0,
            object_id=target.object_id,
            extra={"resolution_note": clean, "comment_author": root.author},
        )
        self._tell_thread(db, product, actor, root, target, NOTIFY_RESOLVED, clean, base_url)
        return self.serialize(db, [root], actor)[0]

    def reopen(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        identity: UserIdentity,
        comment_uuid: str,
        *,
        base_url: str = "",
    ) -> dict[str, Any]:
        root = self._thread_root(db, product, comment_uuid)
        if root.resolved_at is None:
            return self.serialize(db, [root], actor)[0]
        self._require_may_resolve(db, actor, root)
        target = self._target(db, product, root.target_type, root.target_uuid)
        resolver = root.resolved_by
        root.resolved_by = None
        root.resolved_at = None
        root.resolution_note = None
        root.resolved_in_version_id = None
        db.flush()
        self._audit(
            db,
            ActivityAction.COMMENT_REOPENED,
            identity,
            product,
            root,
            target_name=target.name,
            version_display=target.version_display,
            mentions=[],
            images=0,
            object_id=target.object_id,
            extra={"previously_resolved_by": resolver},
        )
        self._tell_thread(
            db, product, actor, root, target, NOTIFY_REOPENED, "", base_url, only_username=resolver
        )
        return self.serialize(db, [root], actor)[0]

    def _tell_thread(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        root: Comment,
        target: _Target,
        kind: str,
        note: str,
        base_url: str,
        only_username: str | None = None,
    ) -> None:
        """Resolve: the originator and everyone mentioned in the thread. Reopen: who resolved it."""
        audience = {u.id: u for u in self._accounts.product_audience(db, product)}
        ids: list[int] = []
        if only_username:
            ids = [u.id for u in audience.values() if str(u.username).lower() == only_username.lower()]
        else:
            if root.author_user_id:
                ids.append(root.author_user_id)
            thread = [root.id] + list(
                db.scalars(select(Comment.id).where(Comment.parent_id == root.id))
            )
            ids += list(
                db.scalars(select(CommentMention.user_id).where(CommentMention.comment_id.in_(thread)))
            )
        for uid in dict.fromkeys(ids):
            user = audience.get(uid)
            if user is None or (actor.user is not None and user.id == actor.user.id):
                continue
            self._deliver(
                db,
                user=user,
                kind=kind,
                product=product,
                comment=root,
                target=target,
                actor=actor,
                images=0,
                base_url=base_url,
                note=note,
            )

    # ------------------------------------------------------------------ rules
    def _get(self, db: Session, comment_uuid: str) -> Comment:
        row = db.scalar(select(Comment).where(Comment.uuid == comment_uuid))
        if row is None:
            raise NotFoundError("Comment not found.")
        return row

    def find(self, db: Session, comment_uuid: str) -> Comment:
        """The comment (for the API to find its product before checking access)."""
        return self._get(db, comment_uuid)

    def _thread_root(self, db: Session, product: Product, comment_uuid: str) -> Comment:
        row = self._get(db, comment_uuid)
        if row.product_id != product.id or row.deleted_at is not None:
            raise NotFoundError("Comment not found.")
        if row.parent_id is not None:
            row = db.get(Comment, row.parent_id) or row
        return row

    @staticmethod
    def _is_author(actor: Actor, comment: Comment) -> bool:
        if actor.user is not None and comment.author_user_id is not None:
            return comment.author_user_id == actor.user.id
        return comment.author.lower() == actor.username.lower()

    def _may_resolve(self, db: Session, actor: Actor, root: Comment) -> bool:
        if actor.can_resolve_any or self._is_author(actor, root):
            return True
        if actor.user is None:
            return True
        thread = [root.id] + list(db.scalars(select(Comment.id).where(Comment.parent_id == root.id)))
        return (
            db.scalar(
                select(CommentMention.id)
                .where(CommentMention.comment_id.in_(thread))
                .where(CommentMention.user_id == actor.user.id)
                .limit(1)
            )
            is not None
        )

    def _require_may_resolve(self, db: Session, actor: Actor, root: Comment) -> None:
        if not self._may_resolve(db, actor, root):
            raise PermissionDeniedError(
                "Only the person who wrote or was mentioned in this thread, or someone allowed to "
                "resolve comments, can resolve or reopen it."
            )

    # ------------------------------------------------------------------ read
    def serialize(self, db: Session, rows: list[Comment], actor: Actor) -> list[dict[str, Any]]:
        if not rows:
            return []
        ids = [c.id for c in rows]
        images = self._attachments(db, ids)
        mention_rows = db.execute(
            select(CommentMention.comment_id, User.username, User.display_name)
            .join(User, User.id == CommentMention.user_id)
            .where(CommentMention.comment_id.in_(ids))
        ).all()
        mentions: dict[int, list[dict]] = {}
        for cid, username, display in mention_rows:
            mentions.setdefault(cid, []).append(
                {"username": username, "display_name": display or username}
            )
        author_ids = {c.author_user_id for c in rows if c.author_user_id}
        display = {}
        if author_ids:
            display = {
                u.id: (u.display_name or u.username)
                for u in db.scalars(select(User).where(User.id.in_(author_ids)))
            }
        version_ids = {c.version_id for c in rows if c.version_id} | {
            c.resolved_in_version_id for c in rows if c.resolved_in_version_id
        }
        versions = {
            v.id: _version_display(v.revision, v.iteration)
            for v in (
                db.scalars(select(ObjectVersion).where(ObjectVersion.id.in_(version_ids)))
                if version_ids
                else []
            )
        }
        names = self._names(db, rows)
        parent_ids = {c.parent_id for c in rows if c.parent_id}
        parent_uuids = (
            {pid: puuid for pid, puuid in db.execute(select(Comment.id, Comment.uuid).where(Comment.id.in_(parent_ids)))}
            if parent_ids
            else {}
        )
        out: list[dict[str, Any]] = []
        for c in rows:
            deleted = c.deleted_at is not None
            mine = self._is_author(actor, c)
            out.append(
                {
                    "uuid": c.uuid,
                    "parent_uuid": parent_uuids.get(c.parent_id) if c.parent_id else None,
                    "product_id": c.product_id,
                    "target_type": c.target_type,
                    "target_uuid": c.target_uuid,
                    "target_name": names.get((c.target_type, c.target_uuid), ""),
                    "version_display": versions.get(c.version_id, ""),
                    "author": c.author,
                    "author_display": display.get(c.author_user_id) or c.author,
                    "body": "" if deleted else c.body,
                    "deleted": deleted,
                    "created_at": _iso(c.created_at),
                    "edited_at": _iso(c.edited_at),
                    "mentions": [] if deleted else mentions.get(c.id, []),
                    "images": []
                    if deleted
                    else [
                        {
                            "uuid": a.uuid,
                            "filename": a.filename,
                            "width": a.width,
                            "height": a.height,
                            "size": a.size,
                            "url": f"/api/comment-attachments/{a.uuid}",
                            "thumb_url": f"/api/comment-attachments/{a.uuid}/thumb",
                        }
                        for a in images.get(c.id, [])
                    ],
                    "resolved": c.parent_id is None and c.resolved_at is not None,
                    "resolved_by": c.resolved_by,
                    "resolved_at": _iso(c.resolved_at),
                    "resolution_note": c.resolution_note,
                    "resolved_in_version": versions.get(c.resolved_in_version_id, ""),
                    "can_edit": bool(mine and not deleted),
                    "can_delete": bool((mine or actor.can_admin) and not deleted),
                    "can_resolve": bool(
                        c.parent_id is None and not deleted and self._may_resolve(db, actor, c)
                    ),
                }
            )
        return out

    def list_threads(
        self,
        db: Session,
        product: Product,
        actor: Actor,
        *,
        target_type: str | None = None,
        target_uuid: str | None = None,
        filter: str = "open",
    ) -> list[dict[str, Any]]:
        mode = filter if filter in FILTERS else "open"
        stmt = (
            select(Comment)
            .where(Comment.product_id == product.id)
            .where(Comment.parent_id.is_(None))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
        )
        if target_type:
            stmt = stmt.where(Comment.target_type == target_type)
        if target_uuid:
            stmt = stmt.where(Comment.target_uuid == target_uuid)
        roots = list(db.scalars(stmt))
        if mode == "open":
            roots = [r for r in roots if r.resolved_at is None and not self._gone(db, r)]
        elif mode == "resolved":
            roots = [r for r in roots if r.resolved_at is not None]
        elif mode == "mine":
            roots = [r for r in roots if self._is_author(actor, r)]
        elif mode == "mentions" and actor.user is not None:
            mentioned = self._threads_mentioning(db, product, actor.user.id)
            # Every thread that mentions you, open or resolved (Open / Resolved narrow it by state).
            roots = [r for r in roots if r.id in mentioned]
        elif mode == "mentions":
            roots = []
        # A deleted thread with no replies left carries nothing to show.
        replies_by_root: dict[int, list[Comment]] = {}
        if roots:
            for reply in db.scalars(
                select(Comment)
                .where(Comment.parent_id.in_([r.id for r in roots]))
                .order_by(Comment.created_at.asc(), Comment.id.asc())
            ):
                replies_by_root.setdefault(int(reply.parent_id), []).append(reply)
        roots = [
            r for r in roots if r.deleted_at is None or any(x.deleted_at is None for x in replies_by_root.get(r.id, []))
        ]
        flat: list[Comment] = []
        for r in roots:
            flat.append(r)
            flat.extend(replies_by_root.get(r.id, []))
        serialized = {row["uuid"]: row for row in self.serialize(db, flat, actor)}
        threads: list[dict[str, Any]] = []
        for r in roots:
            head = dict(serialized[r.uuid])
            head["replies"] = [serialized[x.uuid] for x in replies_by_root.get(r.id, [])]
            threads.append(head)
        return threads

    def _gone(self, db: Session, root: Comment) -> bool:
        if root.deleted_at is None:
            return False
        return (
            db.scalar(
                select(Comment.id)
                .where(Comment.parent_id == root.id)
                .where(Comment.deleted_at.is_(None))
                .limit(1)
            )
            is None
        )

    def _threads_mentioning(self, db: Session, product: Product, user_id: int) -> set[int]:
        rows = db.execute(
            select(Comment.id, Comment.parent_id)
            .join(CommentMention, CommentMention.comment_id == Comment.id)
            .where(CommentMention.user_id == user_id)
            .where(Comment.product_id == product.id)
            .where(Comment.deleted_at.is_(None))
        ).all()
        return {int(parent or cid) for cid, parent in rows}

    def summary(self, db: Session, product: Product, actor: Actor) -> dict[str, Any]:
        """Open-thread counts per target, for the glyphs. One call per page, not per row."""
        roots = list(
            db.scalars(
                select(Comment)
                .where(Comment.product_id == product.id)
                .where(Comment.parent_id.is_(None))
                .where(Comment.resolved_at.is_(None))
            )
        )
        roots = [r for r in roots if not self._gone(db, r)]
        mentioned = (
            self._threads_mentioning(db, product, actor.user.id) if actor.user is not None else set()
        )
        targets: dict[str, dict[str, dict[str, int]]] = {}
        total = 0
        mine = 0
        for r in roots:
            slot = targets.setdefault(r.target_type, {}).setdefault(
                r.target_uuid, {"open": 0, "mentions_me": 0}
            )
            slot["open"] += 1
            total += 1
            if r.id in mentioned:
                slot["mentions_me"] += 1
                mine += 1
        return {"open": total, "mentions_me": mine, "targets": targets}

    # ------------------------------------------------------------------ delete paths
    def delete_for_product(self, db: Session, product_id: int) -> None:
        purge_product_comments(db, product_id)

    def delete_for_object(self, db: Session, obj: EngineeringObject) -> None:
        purge_object_comments(db, [obj])


def purge_product_comments(db: Session, product_id: int) -> None:
    """Product delete: every comment, image, mention and notification of the product."""
    ids = list(db.scalars(select(Comment.id).where(Comment.product_id == product_id)))
    db.execute(delete(UserNotification).where(UserNotification.product_id == product_id))
    db.execute(delete(CommentAttachment).where(CommentAttachment.product_id == product_id))
    if ids:
        db.execute(delete(CommentMention).where(CommentMention.comment_id.in_(ids)))
        db.execute(update(Comment).where(Comment.id.in_(ids)).values(parent_id=None))
        db.execute(delete(Comment).where(Comment.id.in_(ids)))


def purge_object_comments(db: Session, objects: list[EngineeringObject]) -> None:
    """Removing files removes their discussion (the audit rows stay)."""
    if not objects:
        return
    object_ids = [o.id for o in objects]
    keys = [o.uuid for o in objects]
    for start in range(0, len(object_ids), 400):
        chunk = object_ids[start : start + 400]
        keys += list(db.scalars(select(ObjectVersion.uuid).where(ObjectVersion.object_id.in_(chunk))))
    ids: list[int] = []
    for start in range(0, len(keys), 400):
        ids += list(
            db.scalars(
                select(Comment.id)
                .where(Comment.target_type.in_([TARGET_OBJECT, TARGET_VERSION]))
                .where(Comment.target_uuid.in_(keys[start : start + 400]))
            )
        )
    if not ids:
        return
    ids += list(db.scalars(select(Comment.id).where(Comment.parent_id.in_(ids))))
    db.execute(delete(UserNotification).where(UserNotification.comment_id.in_(ids)))
    db.execute(delete(CommentAttachment).where(CommentAttachment.comment_id.in_(ids)))
    db.execute(delete(CommentMention).where(CommentMention.comment_id.in_(ids)))
    db.execute(update(Comment).where(Comment.id.in_(ids)).values(parent_id=None))
    db.execute(delete(Comment).where(Comment.id.in_(ids)))
