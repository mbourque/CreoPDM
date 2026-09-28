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
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PROJECTS_CREATE,
    PERMISSION_PROJECTS_DELETE,
    PERMISSION_PROJECTS_EDIT,
    PERMISSION_PROJECTS_ASSIGN,
    PERMISSION_ROLES_ASSIGN,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_PASSWORD,
    UserStatus,
)
from creopdm.exceptions import NotFoundError, PermissionDeniedError, ValidationAppError
from creopdm.models.project import Project
from creopdm.models.user import Permission, Role, RolePermission, User, UserProject, UserRole
from creopdm.utils.passwords import hash_password, verify_password

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,64}$")
_ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ._/-]{0,62}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


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
                .options(
                    selectinload(User.roles).selectinload(Role.permissions),
                    selectinload(User.projects),
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

    def can_assign_projects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_ASSIGN)

    def can_manage_roles(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_ROLES_MANAGE)

    def can_manage_settings(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_SETTINGS_MANAGE)

    def is_full_administrator(self, user: User) -> bool:
        """True when the user has all CreoPDM Administration caps on one account."""
        return ADMINISTRATION_PERMISSION_KEYS.issubset(self.permission_keys_for_user(user))

    def role_is_full_administrator(self, role: Role) -> bool:
        keys = {p.key for p in (role.permissions or [])}
        return ADMINISTRATION_PERMISSION_KEYS.issubset(keys)

    def can_edit_user(self, actor: User, target: User) -> bool:
        try:
            self.ensure_can_edit_user(actor, target)
            return True
        except ValidationAppError:
            return False

    def ensure_can_edit_user(self, actor: User, target: User) -> None:
        """Non-admins may not self-edit; full admins may edit themselves and other admins."""
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

    def ensure_can_assign_projects(self, actor: User) -> None:
        if not self.can_assign_projects(actor):
            raise PermissionDeniedError(
                "You do not have permission to assign project membership (projects.assign)."
            )

    def ensure_can_assign_role(self, actor: User, role: Role) -> None:
        """Require roles.assign; full-admin roles need a full administrator actor."""
        if not self.can_assign_roles(actor):
            raise PermissionDeniedError(
                "You do not have permission to assign roles (roles.assign)."
            )
        if self.role_is_full_administrator(role) and not self.is_full_administrator(actor):
            raise ValidationAppError(
                "Only a full administrator can assign a full administrator role."
            )

    def assignable_roles_for(self, db: Session, actor: User) -> list[Role]:
        """Roles the actor may pick on Add/Edit user (hides full-admin roles for non-admins)."""
        if not self.can_assign_roles(actor):
            return []
        roles = self.list_roles(db)
        if self.is_full_administrator(actor):
            return roles
        return [r for r in roles if not self.role_is_full_administrator(r)]

    def can_manage_projects(self, user: User) -> bool:
        """True when the user may open Administration → Projects (create/edit/delete)."""
        return (
            self.can_create_project(user)
            or self.can_edit_project(user)
            or self.can_delete_project(user)
        )

    def can_create_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_CREATE)

    def can_edit_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_EDIT)

    def can_delete_project(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_PROJECTS_DELETE)

    def can_add_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_ADD)

    def can_view_objects(self, user: User) -> bool:
        return self.has_permission(user, PERMISSION_OBJECTS_VIEW)

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

        Full admin means users.manage + roles.manage + settings.manage on the
        same account so Users, Roles, and Settings cannot all become unreachable.
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
    ) -> Role:
        self.ensure_permission_catalog(db)
        role = self.get_role_by_uuid(db, role_uuid)
        if role is None:
            raise NotFoundError("Role not found.")
        if name is not None:
            rname = validate_role_name(name)
            other = self.role_by_name(db, rname)
            if other is not None and other.id != role.id:
                raise ValidationAppError(f"Role '{rname}' already exists.")
            role.name = rname
        if description is not None:
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
                    "projects.assign, and settings.manage)."
                )
            db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
            for perm_id in self._permission_ids_for_keys(db, keys):
                db.add(RolePermission(role_id=role.id, permission_id=perm_id))
        role.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_role_by_uuid(db, role.uuid) or role

    def delete_role(self, db: Session, role_uuid: str) -> None:
        role = self.get_role_by_uuid(db, role_uuid)
        if role is None:
            raise NotFoundError("Role not found.")
        if role.users:
            raise ValidationAppError(
                "Cannot delete a role that is still assigned to users. Reassign them first."
            )
        if self._would_leave_zero_full_administrators(db, deleting_role_id=role.id):
            raise ValidationAppError(
                "Cannot delete the last role that grants full CreoPDM Administration "
                "(users, roles, and settings) to an active user."
            )
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.delete(role)
        db.flush()

    def user_can_access_project(self, user: User, project: Project) -> bool:
        """True when the user may browse/use the given project."""
        if getattr(user, "access_all_projects", True):
            return True
        allowed_ids = {p.id for p in (user.projects or [])}
        return project.id in allowed_ids

    def filter_accessible_projects(self, user: User, projects: list[Project]) -> list[Project]:
        if getattr(user, "access_all_projects", True):
            return list(projects)
        allowed_ids = {p.id for p in (user.projects or [])}
        return [p for p in projects if p.id in allowed_ids]

    def set_project_access(
        self,
        db: Session,
        user: User,
        *,
        access_all: bool,
        project_uuids: list[str] | None = None,
    ) -> User:
        """Set All-projects flag and optional membership list (when not all)."""
        user.access_all_projects = bool(access_all)
        if access_all:
            user.updated_at = datetime.now(timezone.utc)
            db.flush()
            return self.get_by_uuid(db, user.uuid) or user
        # Restricted: replace membership. Empty list = no project access (cannot use app browse).
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in project_uuids or []:
            uid = (raw or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            wanted.append(uid)
        projects: list[Project] = []
        for uid in wanted:
            project = db.scalar(select(Project).where(Project.uuid == uid))
            if project is None:
                raise ValidationAppError(f"Unknown project '{uid}'.")
            projects.append(project)
        db.execute(delete(UserProject).where(UserProject.user_id == user.id))
        for project in projects:
            db.add(UserProject(user_id=user.id, project_id=project.id))
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
        return self.get_by_uuid(db, user.uuid) or user

    def grant_project_access(self, db: Session, user: User, project: Project) -> None:
        """Add one project to a restricted user's membership (no-op if all-projects)."""
        if getattr(user, "access_all_projects", True):
            return
        existing = db.scalar(
            select(UserProject).where(
                UserProject.user_id == user.id,
                UserProject.project_id == project.id,
            )
        )
        if existing is not None:
            return
        db.add(UserProject(user_id=user.id, project_id=project.id))
        db.flush()

    def create_user(
        self,
        db: Session,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str | None = None,
        role_name: str = StarterRole.ENGINEER.value,
        must_change_password: bool = False,
        status: str = UserStatus.ACTIVE.value,
        access_all_projects: bool = True,
        project_uuids: list[str] | None = None,
        actor: User | None = None,
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
        if actor is not None:
            self.ensure_can_set_password(actor)
            if not self.can_assign_roles(actor):
                # Edit-users-only: new accounts always land on Engineer.
                role = self.role_by_name(db, StarterRole.ENGINEER.value)
                if role is None:
                    raise ValidationAppError("Engineer role is missing.")
            else:
                self.ensure_can_assign_role(actor, role)
            if not self.can_assign_projects(actor):
                access_all_projects = True
                project_uuids = None
        user = User(
            uuid=str(uuid.uuid4()),
            username=uname,
            display_name=display,
            email=(email or "").strip() or None,
            password_hash=hash_password(pwd),
            status=status,
            must_change_password=must_change_password,
            access_all_projects=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.flush()
        self.set_project_access(
            db,
            user,
            access_all=access_all_projects,
            project_uuids=project_uuids,
        )
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
            role_name=StarterRole.ADMINISTRATOR.value,
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
        access_all_projects: bool | None = None,
        project_uuids: list[str] | None = None,
        actor: User | None = None,
    ) -> User:
        user = self.get_by_uuid(db, user_uuid)
        if user is None:
            raise NotFoundError("User not found.")
        if actor is not None:
            self.ensure_can_edit_user(actor, user)
        if display_name is not None:
            text = display_name.strip()
            if not text:
                raise ValidationAppError("Display name is required.")
            user.display_name = text
        if email is not None:
            user.email = email.strip() or None
        new_status = status
        if status is not None:
            if status not in {UserStatus.ACTIVE.value, UserStatus.DISABLED.value}:
                raise ValidationAppError("Invalid status.")
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
                    "projects.assign, and settings.manage)."
                )
        if new_status is not None:
            user.status = new_status
        if new_role_id is not None:
            db.execute(delete(UserRole).where(UserRole.user_id == user.id))
            db.add(UserRole(user_id=user.id, role_id=new_role_id))
        if access_all_projects is not None:
            if actor is not None and not self.can_assign_projects(actor):
                current_all = bool(getattr(user, "access_all_projects", True))
                current_ids = {p.uuid for p in (user.projects or [])}
                wanted_ids = (
                    set()
                    if access_all_projects
                    else {str(u).strip() for u in (project_uuids or []) if str(u).strip()}
                )
                if bool(access_all_projects) != current_all or (
                    not access_all_projects and wanted_ids != current_ids
                ):
                    self.ensure_can_assign_projects(actor)
                access_all_projects = None
            if access_all_projects is not None:
                self.set_project_access(
                    db,
                    user,
                    access_all=access_all_projects,
                    project_uuids=project_uuids if not access_all_projects else None,
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
