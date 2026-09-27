"""User and role persistence for session auth."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from creopdm.auth_constants import (
    BUILTIN_PERMISSIONS,
    BUILTIN_ROLE_DESCRIPTIONS,
    ROLE_PERMISSION_KEYS,
    BuiltinRole,
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_PROJECTS_CREATE,
    PERMISSION_PROJECTS_DELETE,
    PERMISSION_PROJECTS_EDIT,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_USERS_MANAGE,
    UserStatus,
)
from creopdm.exceptions import NotFoundError, ValidationAppError
from creopdm.models.user import Permission, Role, RolePermission, User, UserRole
from creopdm.utils.passwords import hash_password, verify_password

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,64}$")


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str:
    value = _normalize_username(username)
    if not _USERNAME_RE.match(value):
        raise ValidationAppError(
            "Username must be 2–64 characters: letters, numbers, dot, underscore, or hyphen."
        )
    return value


def validate_password(password: str) -> str:
    text = password or ""
    if len(text) < 8:
        raise ValidationAppError("Password must be at least 8 characters.")
    return text


class UserService:
    def user_count(self, db: Session) -> int:
        return int(db.scalar(select(func.count()).select_from(User)) or 0)

    def needs_setup(self, db: Session) -> bool:
        return self.user_count(db) == 0

    def ensure_builtin_roles(self, db: Session) -> None:
        """Idempotent seed for roles/permissions (migration also seeds; safe to re-run)."""
        for name, description in BUILTIN_ROLE_DESCRIPTIONS.items():
            existing = db.scalar(select(Role).where(Role.name == name))
            if existing is None:
                db.add(
                    Role(
                        uuid=str(uuid.uuid4()),
                        name=name,
                        description=description,
                        is_builtin=True,
                    )
                )
        for key, description in BUILTIN_PERMISSIONS:
            existing = db.scalar(select(Permission).where(Permission.key == key))
            if existing is None:
                db.add(Permission(key=key, description=description))
        db.flush()
        for role_name, keys in ROLE_PERMISSION_KEYS.items():
            role = db.scalar(select(Role).where(Role.name == role_name))
            if role is None:
                continue
            for key in keys:
                perm = db.scalar(select(Permission).where(Permission.key == key))
                if perm is None:
                    continue
                link = db.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if link is None:
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.flush()

    def permission_keys_for_user(self, user: User) -> frozenset[str]:
        if any(role.name == BuiltinRole.ADMINISTRATOR.value for role in user.roles):
            return frozenset(key for key, _ in BUILTIN_PERMISSIONS)
        keys: set[str] = set()
        for role in user.roles:
            for perm in role.permissions:
                keys.add(perm.key)
            keys.update(ROLE_PERMISSION_KEYS.get(role.name, ()))
        return frozenset(keys)

    def get_by_uuid(self, db: Session, user_uuid: str) -> User | None:
        return db.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.uuid == user_uuid)
        )

    def get_by_username(self, db: Session, username: str) -> User | None:
        return db.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.username == _normalize_username(username))
        )

    def list_users(self, db: Session) -> list[User]:
        return list(
            db.scalars(
                select(User)
                .options(selectinload(User.roles))
                .order_by(User.username)
            ).all()
        )

    def list_roles(self, db: Session) -> list[Role]:
        return list(db.scalars(select(Role).order_by(Role.name)).all())

    def role_by_name(self, db: Session, name: str) -> Role | None:
        return db.scalar(select(Role).where(Role.name == name))

    def primary_role_name(self, user: User) -> str:
        if not user.roles:
            return ""
        return user.roles[0].name

    def has_permission(self, user: User, key: str) -> bool:
        for role in user.roles:
            for perm in role.permissions:
                if perm.key == key:
                    return True
            if role.name == BuiltinRole.ADMINISTRATOR.value:
                return True
        return False

    def can_manage_users(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_USERS_MANAGE)

    def can_manage_settings(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_SETTINGS_MANAGE)

    def can_create_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_CREATE)

    def can_edit_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_EDIT)

    def can_delete_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_DELETE)

    def can_add_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_ADD)

    def can_checkout(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_CHECKOUT)

    def can_checkin(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_CHECKIN)

    def can_remove_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_REMOVE)

    def can_revert_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_REVERT)

    def can_update_metadata(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_METADATA)

    def create_user(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str | None = None,
        role_name: str = BuiltinRole.ENGINEER.value,
        must_change_password: bool = False,
        status: str = UserStatus.ACTIVE.value,
    ) -> User:
        self.ensure_builtin_roles(db)
        uname = validate_username(username)
        if self.get_by_username(db, uname) is not None:
            raise ValidationAppError(f"Username '{uname}' is already taken.")
        display = (display_name or "").strip() or uname
        pwd = validate_password(password)
        role = self.role_by_name(db, role_name)
        if role is None:
            raise ValidationAppError(f"Unknown role '{role_name}'.")
        user = User(
            uuid=str(uuid.uuid4()),
            username=uname,
            display_name=display,
            email=(email or "").strip() or None,
            password_hash=hash_password(pwd),
            status=status,
            must_change_password=must_change_password,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.flush()
        return self.get_by_uuid(db, user.uuid) or user

    def create_first_admin(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        password: str,
    ) -> User:
        if not self.needs_setup(db):
            raise ValidationAppError("Setup is already complete.")
        return self.create_user(
            db,
            username=username,
            display_name=display_name,
            password=password,
            role_name=BuiltinRole.ADMINISTRATOR.value,
            must_change_password=False,
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
    ) -> User:
        user = self.get_by_uuid(db, user_uuid)
        if user is None:
            raise NotFoundError("User not found.")
        if display_name is not None:
            text = display_name.strip()
            if not text:
                raise ValidationAppError("Display name is required.")
            user.display_name = text
        if email is not None:
            user.email = email.strip() or None
        if status is not None:
            if status not in {UserStatus.ACTIVE.value, UserStatus.DISABLED.value}:
                raise ValidationAppError("Invalid status.")
            user.status = status
        if password:
            user.password_hash = hash_password(validate_password(password))
        if must_change_password is not None:
            user.must_change_password = must_change_password
        if role_name is not None:
            role = self.role_by_name(db, role_name)
            if role is None:
                raise ValidationAppError(f"Unknown role '{role_name}'.")
            db.execute(delete(UserRole).where(UserRole.user_id == user.id))
            db.add(UserRole(user_id=user.id, role_id=role.id))
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
