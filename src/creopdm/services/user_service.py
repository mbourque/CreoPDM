"""User and role persistence for session auth."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from creopdm.auth_constants import (
    ADMINISTRATION_PERMISSION_KEYS,
    BUILTIN_PERMISSIONS,
    STARTER_ROLE_DESCRIPTIONS,
    STARTER_ROLE_PERMISSION_KEYS,
    StarterRole,
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_COPY_TO_VAULT,
    PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PRODUCTS_CREATE,
    PERMISSION_PRODUCTS_DELETE,
    PERMISSION_PRODUCTS_EDIT,
    PERMISSION_PRODUCTS_MANAGE,
    PERMISSION_PRODUCTS_VIEW,
    PERMISSION_PRODUCTS_ASSIGN,
    PERMISSION_ROLES_ASSIGN,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_SETTINGS_AI,
    PERMISSION_EMAIL_MANAGE,
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_PASSWORD,
    PERMISSION_UTILITIES_AUDIT,
    PERMISSION_UTILITIES_AVAILABILITY,
    PERMISSION_UTILITIES_COMPACT_PRODUCT,
    PERMISSION_UTILITIES_DELETE_PRODUCT,
    PERMISSION_UTILITIES_EMAIL_USERS,
    PERMISSION_UTILITIES_HEALTH,
    PERMISSION_UTILITIES_LOGS,
    PERMISSION_UTILITIES_REBUILD_PRODUCT,
    UTILITIES_PERMISSION_KEYS,
    UserStatus,
)
from creopdm.exceptions import NotFoundError, PermissionDeniedError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.product import Product
from creopdm.models.user import Permission, Role, RolePermission, User, UserProduct, UserRole
from creopdm.utils.passwords import hash_password, verify_password

logger = get_logger("user_service")

# Login names: letters, digits, underscore only (no spaces or punctuation).
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{2,64}$")
_ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ._/-]{0,62}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


def _normalize_username(username: str) -> str:
    return (username or "").strip().casefold()


def validate_username(username: str) -> str:
    value = _normalize_username(username)
    if not _USERNAME_RE.match(value):
        raise ValidationAppError(
            "Username must be 2–64 characters: letters, numbers, or underscore only (no spaces)."
        )
    return value


def validate_password(password: str) -> str:
    text = password or ""
    if len(text) < 8:
        raise ValidationAppError("Password must be at least 8 characters.")
    return text


def validate_email(email: str) -> str:
    """Require a real name@domain.tld address (email-validator; no DNS lookup)."""
    from email_validator import EmailNotValidError
    from email_validator import validate_email as validate_email_address

    value = (email or "").strip()
    if not value:
        raise ValidationAppError("Email is required.")
    if len(value) > 255:
        raise ValidationAppError("Enter a valid email address.")
    # Reject dotless domains like user@ca (HTML5 type=email wrongly allows these).
    at = value.rfind("@")
    domain = value[at + 1 :] if at >= 0 else ""
    if "." not in domain or not domain.rsplit(".", 1)[-1].isalpha() or len(domain.rsplit(".", 1)[-1]) < 2:
        raise ValidationAppError("Enter a valid email address.")
    try:
        result = validate_email_address(
            value,
            check_deliverability=False,
            globally_deliverable=True,
        )
    except EmailNotValidError as exc:
        raise ValidationAppError("Enter a valid email address.") from exc
    return str(result.normalized)


def validate_role_name(name: str) -> str:
    value = (name or "").strip()
    if not value or len(value) > 64:
        raise ValidationAppError("Role name must be 1–64 characters.")
    if not _ROLE_NAME_RE.match(value):
        raise ValidationAppError(
            "Role name must start and end with a letter or number."
        )
    return value


class UserService:
    def user_count(self, db: Session) -> int:
        return int(db.scalar(select(func.count()).select_from(User)) or 0)

    def needs_setup(self, db: Session) -> bool:
        return self.user_count(db) == 0

    def ensure_permission_catalog(self, db: Session) -> None:
        """Idempotent insert of known permission keys (never deletes)."""
        for key, description in BUILTIN_PERMISSIONS:
            existing = db.scalar(select(Permission).where(Permission.key == key))
            if existing is None:
                db.add(Permission(key=key, description=description))
            elif existing.description != description:
                existing.description = description
        db.flush()

    def ensure_builtin_roles(self, db: Session) -> None:
        """Ensure permission catalog; seed starter roles only when roles table is empty."""
        self.ensure_permission_catalog(db)
        role_count = int(db.scalar(select(func.count()).select_from(Role)) or 0)
        if role_count > 0:
            return
        for name, description in STARTER_ROLE_DESCRIPTIONS.items():
            db.add(
                Role(
                    uuid=str(uuid.uuid4()),
                    name=name,
                    description=description,
                    is_builtin=False,
                )
            )
        db.flush()
        for role_name, keys in STARTER_ROLE_PERMISSION_KEYS.items():
            role = db.scalar(select(Role).where(Role.name == role_name))
            if role is None:
                continue
            for key in keys:
                perm = db.scalar(select(Permission).where(Permission.key == key))
                if perm is None:
                    continue
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.flush()

    def permission_keys_for_user(self, user: User) -> frozenset[str]:
        """Caps from DB role_permissions only (no name-based short-circuit)."""
        keys: set[str] = set()
        for role in user.roles:
            for perm in role.permissions:
                keys.add(perm.key)
        return frozenset(keys)

    def get_by_uuid(self, db: Session, user_uuid: str) -> User | None:
        # Always load products: restricted users (access_all_products=False) need
        # membership on request.state.auth_user after the auth middleware session closes.
        return db.scalar(
            select(User)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.products),
            )
            .where(User.uuid == user_uuid)
        )

    def get_by_username(self, db: Session, username: str) -> User | None:
        return db.scalar(
            select(User)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.products),
            )
            .where(User.username == _normalize_username(username))
        )

    def list_users(self, db: Session) -> list[User]:
        return list(
            db.scalars(
                select(User)
                .options(
                    selectinload(User.roles).selectinload(Role.permissions),
                    selectinload(User.products),
                )
                .order_by(User.username)
            ).all()
        )

    def list_roles(self, db: Session) -> list[Role]:
        return list(
            db.scalars(
                select(Role)
                .options(selectinload(Role.permissions), selectinload(Role.users))
                .order_by(Role.name)
            ).all()
        )

    def get_role_by_uuid(self, db: Session, role_uuid: str) -> Role | None:
        return db.scalar(
            select(Role)
            .options(selectinload(Role.permissions), selectinload(Role.users))
            .where(Role.uuid == role_uuid)
        )

    def role_by_name(self, db: Session, name: str) -> Role | None:
        return db.scalar(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.name == (name or "").strip())
        )

    def list_permissions(self, db: Session) -> list[Permission]:
        self.ensure_permission_catalog(db)
        return list(db.scalars(select(Permission).order_by(Permission.key)).all())

    def primary_role_name(self, user: User) -> str:
        if not user.roles:
            return ""
        return user.roles[0].name

    def primary_role_uuid(self, user: User) -> str | None:
        if not user.roles:
            return None
        return user.roles[0].uuid

    def has_permission(self, user: User, key: str) -> bool:
        return key in self.permission_keys_for_user(user)

    def can_manage_users(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_USERS_MANAGE)

    def can_set_passwords(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_USERS_PASSWORD)

    def can_assign_roles(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_ROLES_ASSIGN)

    def can_assign_products(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PRODUCTS_ASSIGN)

    def can_manage_roles(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_ROLES_MANAGE)

    def can_manage_settings(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_SETTINGS_MANAGE)

    def can_manage_ai(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_SETTINGS_AI)

    def can_manage_email(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_EMAIL_MANAGE)

    def can_access_utilities(self, user: User) -> bool:
        """True when the user may open Administration → Utilities (any tool)."""
        return bool(self.permission_keys_for_user(user) & UTILITIES_PERMISSION_KEYS)

    def can_utilities_availability(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_AVAILABILITY)

    def can_utilities_email_users(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_EMAIL_USERS)

    def can_utilities_compact_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_COMPACT_PRODUCT)

    def can_utilities_rebuild_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_REBUILD_PRODUCT)

    def can_utilities_delete_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_DELETE_PRODUCT)

    def can_utilities_audit(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_AUDIT)

    def can_utilities_health(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_HEALTH)

    def can_utilities_logs(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_UTILITIES_LOGS)

    def is_full_administrator(self, user: User) -> bool:
        """True when the user has all CreoPDM Administration caps on one account."""
        return ADMINISTRATION_PERMISSION_KEYS.issubset(self.permission_keys_for_user(user))

    def role_is_full_administrator(self, role: Role) -> bool:
        keys = {p.key for p in (role.permissions or [])}
        return ADMINISTRATION_PERMISSION_KEYS.issubset(keys)

    def user_holds_role(self, user: User, role: Role) -> bool:
        return any(r.id == role.id for r in (user.roles or []))

    def can_edit_user(self, actor: User, target: User) -> bool:
        try:
            self.ensure_can_edit_user(actor, target)
            return True
        except ValidationAppError:
            return False

    def ensure_can_edit_user(self, actor: User, target: User) -> None:
        """Non-admins may not self-edit; full admins may edit themselves (not own role/status) and other admins."""
        if actor.id == target.id:
            if not self.is_full_administrator(actor):
                raise ValidationAppError(
                    "You cannot edit your own account. Ask another administrator."
                )
            return
        if self.is_full_administrator(target) and not self.is_full_administrator(actor):
            raise ValidationAppError(
                "Only a full administrator can edit another administrator."
            )

    def ensure_can_set_password(self, actor: User) -> None:
        if not self.can_set_passwords(actor):
            raise PermissionDeniedError(
                "You do not have permission to set passwords (users.password)."
            )

    def ensure_can_assign_products(self, actor: User) -> None:
        if not self.can_assign_products(actor):
            raise PermissionDeniedError(
                "You do not have permission to assign product membership (products.assign)."
            )

    def role_permission_keys(self, role: Role) -> frozenset[str]:
        return frozenset(p.key for p in (role.permissions or []))

    def role_is_strictly_below(self, actor: User, role: Role) -> bool:
        """True when role permissions are a proper subset of the actor's caps."""
        actor_keys = self.permission_keys_for_user(actor)
        role_keys = self.role_permission_keys(role)
        return role_keys < actor_keys

    def ensure_can_assign_role(self, actor: User, role: Role) -> None:
        """Require roles.assign. Full admins may assign any role; others only strictly below."""
        if not self.can_assign_roles(actor):
            raise PermissionDeniedError(
                "You do not have permission to assign roles (roles.assign)."
            )
        if self.is_full_administrator(actor):
            return
        if not self.role_is_strictly_below(actor, role):
            raise ValidationAppError(
                "You can only assign a role with fewer permissions than your own "
                "(not the same role or a higher one)."
            )

    def assignable_roles_for(self, db: Session, actor: User) -> list[Role]:
        """Roles the actor may pick on Add/Edit user.

        Full administrators see every role (including Administrator). Other
        accounts with roles.assign only see roles strictly below their own caps.
        """
        if not self.can_assign_roles(actor):
            return []
        roles = self.list_roles(db)
        if self.is_full_administrator(actor):
            return roles
        return [r for r in roles if self.role_is_strictly_below(actor, r)]

    def can_manage_products(self, user: User) -> bool:
        """True when the user may open Administration → Products (full CRUD there)."""
        return self.has_permission(user, PERMISSION_PRODUCTS_MANAGE)

    def can_create_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PRODUCTS_CREATE)

    def can_edit_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PRODUCTS_EDIT)

    def can_delete_product(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PRODUCTS_DELETE)

    def can_view_products(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PRODUCTS_VIEW)

    def can_add_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_ADD)

    def can_view_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_VIEW)

    def can_checkout(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_CHECKOUT)

    def can_checkin(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_CHECKIN)

    def can_force_undo_checkout(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT)

    def can_remove_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_REMOVE)

    def can_revert_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_REVERT)

    def can_update_metadata(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_METADATA)

    def can_copy_to_vault(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_COPY_TO_VAULT)

    def count_active_users_with_permission(self, db: Session, key: str) -> int:
        users = db.scalars(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.status == UserStatus.ACTIVE.value)
        ).all()
        return sum(1 for user in users if key in self.permission_keys_for_user(user))

    def _permission_ids_for_keys(self, db: Session, keys: set[str] | frozenset[str]) -> list[int]:
        if not keys:
            return []
        known = {key for key, _ in BUILTIN_PERMISSIONS}
        unknown = set(keys) - known
        if unknown:
            raise ValidationAppError(f"Unknown permission key(s): {', '.join(sorted(unknown))}.")
        rows = list(db.scalars(select(Permission).where(Permission.key.in_(list(keys)))).all())
        if len(rows) != len(keys):
            raise ValidationAppError("One or more permission keys are not in the catalog.")
        return [row.id for row in rows]

    def _would_leave_zero_full_administrators(
        self,
        db: Session,
        *,
        exclude_user_id: int | None = None,
        role_id: int | None = None,
        role_keys: frozenset[str] | None = None,
        deleting_role_id: int | None = None,
        user_new_role_id: int | None = None,
        user_new_status: str | None = None,
    ) -> bool:
        """True when no ACTIVE user would keep all CreoPDM Administration caps.

        Full admin means every ADMINISTRATION_PERMISSION_KEYS entry on the
        same account so Users, Roles, Products admin, and Settings cannot
        all become unreachable.
        """
        users = list(
            db.scalars(
                select(User)
                .options(selectinload(User.roles).selectinload(Role.permissions))
            ).all()
        )
        roles_by_id = {
            role.id: role
            for role in db.scalars(
                select(Role).options(selectinload(Role.permissions))
            ).all()
        }
        for user in users:
            status = user.status
            if exclude_user_id is not None and user.id == exclude_user_id and user_new_status is not None:
                status = user_new_status
            if status != UserStatus.ACTIVE.value:
                continue
            keys: set[str] = set()
            role_ids = [r.id for r in user.roles]
            if exclude_user_id is not None and user.id == exclude_user_id and user_new_role_id is not None:
                role_ids = [user_new_role_id]
            for rid in role_ids:
                if deleting_role_id is not None and rid == deleting_role_id:
                    continue
                if role_id is not None and rid == role_id and role_keys is not None:
                    keys.update(role_keys)
                    continue
                role = roles_by_id.get(rid)
                if role is None:
                    continue
                keys.update(p.key for p in role.permissions)
            if ADMINISTRATION_PERMISSION_KEYS.issubset(keys):
                return False
        return True

    # Back-compat alias for callers/tests that used the old name.
    _would_leave_zero_users_manage = _would_leave_zero_full_administrators

    def create_role(
        self,
        db: Session,
        *,
        name: str,
        description: str = "",
        permission_keys: list[str] | None = None,
    ) -> Role:
        self.ensure_permission_catalog(db)
        rname = validate_role_name(name)
        if self.role_by_name(db, rname) is not None:
            raise ValidationAppError(f"Role '{rname}' already exists.")
        keys = frozenset(permission_keys or [])
        role = Role(
            uuid=str(uuid.uuid4()),
            name=rname,
            description=(description or "").strip(),
            is_builtin=False,
        )
        db.add(role)
        db.flush()
        for perm_id in self._permission_ids_for_keys(db, keys):
            db.add(RolePermission(role_id=role.id, permission_id=perm_id))
        db.flush()
        return self.get_role_by_uuid(db, role.uuid) or role

    def update_role(
        self,
        db: Session,
        role_uuid: str,
        *,
        name: str | None = None,
        description: str | None = None,
        permission_keys: list[str] | None = None,
        actor: User | None = None,
    ) -> Role:
        self.ensure_permission_catalog(db)
        role = self.get_role_by_uuid(db, role_uuid)
        if role is None:
            raise NotFoundError("Role not found.")
        editing_own = actor is not None and self.user_holds_role(actor, role)
        current_keys = {p.key for p in (role.permissions or [])}
        if editing_own:
            if name is not None and validate_role_name(name) != role.name:
                raise ValidationAppError(
                    "You cannot rename a role assigned to you. Ask another administrator."
                )
            if description is not None and (description or "").strip() != (role.description or "").strip():
                raise ValidationAppError(
                    "You cannot change the description of a role assigned to you. "
                    "Ask another administrator."
                )
            if permission_keys is not None:
                new_keys = frozenset(permission_keys)
                current_admin = current_keys & ADMINISTRATION_PERMISSION_KEYS
                new_admin = new_keys & ADMINISTRATION_PERMISSION_KEYS
                if new_admin != current_admin:
                    raise ValidationAppError(
                        "You cannot change CreoPDM Administration permissions on a role "
                        "assigned to you. Ask another administrator."
                    )
        if name is not None and not editing_own:
            rname = validate_role_name(name)
            other = self.role_by_name(db, rname)
            if other is not None and other.id != role.id:
                raise ValidationAppError(f"Role '{rname}' already exists.")
            role.name = rname
        if description is not None and not editing_own:
            role.description = description.strip()
        if permission_keys is not None:
            keys = frozenset(permission_keys)
            if self._would_leave_zero_full_administrators(
                db, role_id=role.id, role_keys=keys
            ):
                raise ValidationAppError(
                    "Cannot leave the system with no active user who has full "
                    "CreoPDM Administration "
                    "(users.manage, users.password, roles.assign, roles.manage, "
                    "products.assign, products.manage, settings.manage, settings.ai, "
                    "email.manage, and all utilities.* permissions)."
                )
            db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
            for perm_id in self._permission_ids_for_keys(db, keys):
                db.add(RolePermission(role_id=role.id, permission_id=perm_id))
        role.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_role_by_uuid(db, role.uuid) or role

    def delete_role(
        self, db: Session, role_uuid: str, *, actor: User | None = None
    ) -> None:
        role = self.get_role_by_uuid(db, role_uuid)
        if role is None:
            raise NotFoundError("Role not found.")
        if actor is not None and self.user_holds_role(actor, role):
            raise ValidationAppError(
                "You cannot delete a role assigned to you. Ask another administrator."
            )
        if role.users:
            raise ValidationAppError(
                "Cannot delete a role that is still assigned to users. Reassign them first."
            )
        if self._would_leave_zero_full_administrators(db, deleting_role_id=role.id):
            raise ValidationAppError(
                "Cannot delete the last role that grants full CreoPDM Administration "
                "to an active user."
            )
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.delete(role)
        db.flush()

    @staticmethod
    def _membership_product_ids(user: User) -> set[int]:
        """Product ids from user_products. Never raises on detached/unloaded ORM state."""
        try:
            return {p.id for p in (user.products or [])}
        except Exception:
            # DetachedInstanceError when auth middleware closed its session before
            # products were loaded — treat as no membership rather than 500 the UI.
            logger.exception(
                "Could not read product membership for user_id=%s; denying access",
                getattr(user, "id", None),
            )
            return set()

    def user_can_access_product(self, user: User, product: Product) -> bool:
        """True when the user may browse/use the given product."""
        if getattr(user, "access_all_products", True):
            return True
        return product.id in self._membership_product_ids(user)

    def filter_accessible_products(self, user: User, products: list[Product]) -> list[Product]:
        if getattr(user, "access_all_products", True):
            return list(products)
        allowed_ids = self._membership_product_ids(user)
        return [p for p in products if p.id in allowed_ids]

    def set_product_access(
        self,
        db: Session,
        user: User,
        *,
        access_all: bool,
        product_uuids: list[str] | None = None,
    ) -> User:
        """Set All-products flag and optional membership list (when not all)."""
        user.access_all_products = bool(access_all)
        if access_all:
            user.updated_at = datetime.now(timezone.utc)
            db.flush()
            return self.get_by_uuid(db, user.uuid) or user
        # Restricted: replace membership. Empty list = no product access (cannot use app browse).
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in product_uuids or []:
            uid = (raw or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            wanted.append(uid)
        products: list[Product] = []
        for uid in wanted:
            product = db.scalar(select(Product).where(Product.uuid == uid))
            if product is None:
                raise ValidationAppError(f"Unknown product '{uid}'.")
            products.append(product)
        db.execute(delete(UserProduct).where(UserProduct.user_id == user.id))
        for product in products:
            db.add(UserProduct(user_id=user.id, product_id=product.id))
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_by_uuid(db, user.uuid) or user

    def grant_product_access(self, db: Session, user: User, product: Product) -> None:
        """Add one product to a restricted user's membership (no-op if all-products)."""
        if getattr(user, "access_all_products", True):
            return
        existing = db.scalar(
            select(UserProduct).where(
                UserProduct.user_id == user.id,
                UserProduct.product_id == product.id,
            )
        )
        if existing is not None:
            return
        db.add(UserProduct(user_id=user.id, product_id=product.id))
        db.flush()

    def revoke_product_access(self, db: Session, user: User, product: Product) -> None:
        """Remove one product from a restricted user's membership (no-op if all-products)."""
        if getattr(user, "access_all_products", True):
            return
        db.execute(
            delete(UserProduct).where(
                UserProduct.user_id == user.id,
                UserProduct.product_id == product.id,
            )
        )
        db.flush()

    def set_restricted_product_members(
        self,
        db: Session,
        product: Product,
        *,
        member_user_uuids: list[str],
        actor: User | None = None,
    ) -> None:
        """Replace which *restricted* users are members of this product.

        Users with All products are ignored (they already see every product).
        """
        if actor is not None:
            self.ensure_can_assign_products(actor)
        wanted = {str(u).strip() for u in (member_user_uuids or []) if str(u).strip()}
        for user in self.list_users(db):
            if user.status != UserStatus.ACTIVE.value:
                continue
            if getattr(user, "access_all_products", True):
                continue
            if user.uuid in wanted:
                self.grant_product_access(db, user, product)
            else:
                self.revoke_product_access(db, user, product)

    def create_user(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str,
        role_name: str = StarterRole.ENGINEER.value,
        must_change_password: bool = False,
        status: str = UserStatus.ACTIVE.value,
        access_all_products: bool = False,
        product_uuids: list[str] | None = None,
        actor: User | None = None,
    ) -> User:
        self.ensure_builtin_roles(db)
        uname = validate_username(username)
        if self.get_by_username(db, uname) is not None:
            raise ValidationAppError(f"Username '{uname}' is already taken.")
        display = (display_name or "").strip() or uname
        pwd = validate_password(password)
        addr = validate_email(email)
        role = self.role_by_name(db, role_name)
        if role is None:
            raise ValidationAppError(f"Unknown role '{role_name}'.")
        if actor is not None:
            self.ensure_can_set_password(actor)
            if not self.can_assign_roles(actor):
                # Edit-users-only: new accounts always land on Engineer.
                role = self.role_by_name(db, StarterRole.ENGINEER.value)
                if role is None:
                    raise ValidationAppError("Engineer role is missing.")
            else:
                self.ensure_can_assign_role(actor, role)
            if not self.can_assign_products(actor):
                # Cannot grant All products without products.assign — leave none.
                access_all_products = False
                product_uuids = None
        user = User(
            uuid=str(uuid.uuid4()),
            username=uname,
            display_name=display,
            email=addr,
            password_hash=hash_password(pwd),
            status=status,
            must_change_password=must_change_password,
            access_all_products=False,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.flush()
        self.set_product_access(
            db,
            user,
            access_all=access_all_products,
            product_uuids=product_uuids,
        )
        return self.get_by_uuid(db, user.uuid) or user

    def create_first_admin(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str,
    ) -> User:
        if not self.needs_setup(db):
            raise ValidationAppError("Setup is already complete.")
        return self.create_user(
            db,
            username=username,
            display_name=display_name,
            password=password,
            email=email,
            role_name=StarterRole.ADMINISTRATOR.value,
            must_change_password=False,
            access_all_products=True,
        )

    def authenticate(self, db: Session, username: str, password: str) -> User:
        user = self.get_by_username(db, username)
        if user is None or not verify_password(password, user.password_hash):
            raise ValidationAppError("Invalid username or password.")
        if user.status != UserStatus.ACTIVE.value:
            raise ValidationAppError("This account is disabled.")
        user.last_login_at = datetime.now(timezone.utc)
        db.flush()
        return user

    def update_user(
        self,
        db: Session,
        user_uuid: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        role_name: str | None = None,
        status: str | None = None,
        password: str | None = None,
        must_change_password: bool | None = None,
        access_all_products: bool | None = None,
        product_uuids: list[str] | None = None,
        actor: User | None = None,
    ) -> User:
        user = self.get_by_uuid(db, user_uuid)
        if user is None:
            raise NotFoundError("User not found.")
        if actor is not None:
            self.ensure_can_edit_user(actor, user)
        editing_self = actor is not None and actor.id == user.id
        if display_name is not None:
            text = display_name.strip()
            if not text:
                raise ValidationAppError("Display name is required.")
            user.display_name = text
        if email is not None:
            user.email = validate_email(email)
        new_status = status
        if status is not None:
            if status not in {UserStatus.ACTIVE.value, UserStatus.DISABLED.value}:
                raise ValidationAppError("Invalid status.")
            if editing_self and status != user.status:
                raise ValidationAppError(
                    "You cannot change your own status. Ask another administrator."
                )
        if password:
            if actor is not None:
                self.ensure_can_set_password(actor)
            user.password_hash = hash_password(validate_password(password))
        if must_change_password is not None:
            user.must_change_password = must_change_password
        new_role_id = None
        if role_name is not None:
            current_role = self.primary_role_name(user)
            if (role_name or "").strip() == current_role:
                role_name = None
            else:
                if editing_self:
                    raise ValidationAppError(
                        "You cannot change your own role. Ask another administrator."
                    )
                role = self.role_by_name(db, role_name)
                if role is None:
                    raise ValidationAppError(f"Unknown role '{role_name}'.")
                if actor is not None:
                    self.ensure_can_assign_role(actor, role)
                new_role_id = role.id
        if role_name is not None or new_status is not None:
            if self._would_leave_zero_full_administrators(
                db,
                exclude_user_id=user.id,
                user_new_role_id=new_role_id,
                user_new_status=new_status if new_status is not None else user.status,
            ):
                raise ValidationAppError(
                    "Cannot leave the system with no active user who has full "
                    "CreoPDM Administration "
                    "(users.manage, users.password, roles.assign, roles.manage, "
                    "products.assign, products.manage, settings.manage, settings.ai, "
                    "email.manage, and all utilities.* permissions)."
                )
        if new_status is not None:
            user.status = new_status
        if new_role_id is not None:
            db.execute(delete(UserRole).where(UserRole.user_id == user.id))
            db.add(UserRole(user_id=user.id, role_id=new_role_id))
        if access_all_products is not None:
            if actor is not None and not self.can_assign_products(actor):
                current_all = bool(getattr(user, "access_all_products", True))
                current_ids = {p.uuid for p in (user.products or [])}
                wanted_ids = (
                    set()
                    if access_all_products
                    else {str(u).strip() for u in (product_uuids or []) if str(u).strip()}
                )
                if bool(access_all_products) != current_all or (
                    not access_all_products and wanted_ids != current_ids
                ):
                    self.ensure_can_assign_products(actor)
                access_all_products = None
            if access_all_products is not None:
                self.set_product_access(
                    db,
                    user,
                    access_all=access_all_products,
                    product_uuids=product_uuids if not access_all_products else None,
                )
                return self.get_by_uuid(db, user.uuid) or user
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_by_uuid(db, user.uuid) or user

    def change_password(self, db: Session, user: User, current: str, new_password: str) -> None:
        if not verify_password(current, user.password_hash):
            raise ValidationAppError("Current password is incorrect.")
        user.password_hash = hash_password(validate_password(new_password))
        user.must_change_password = False
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
