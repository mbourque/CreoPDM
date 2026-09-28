"""HTML + form endpoints for setup, login, logout, password, and user admin."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response
from creopdm.auth_constants import (
    ADMINISTRATION_PERMISSION_KEYS,
    BUILTIN_PERMISSIONS,
    PERMISSION_GROUPS,
    StarterRole,
    UserStatus,
)
from creopdm.auth_session import SESSION_USER_KEY
from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.context import AppContext
from creopdm.exceptions import CreoPDMError
from creopdm.models.user import User
from creopdm.permissions import (
    can_open_administration,
    caps_dict,
    caps_for_user,
    default_app_path,
    resolve_post_login_target,
)
from creopdm.utils.identity import UserIdentity, set_request_identity

# Back-compat for default form role.
BuiltinRole = StarterRole

PACKAGE_DIR = Path(__file__).resolve().parent.parent
_template_env = Environment(
    loader=FileSystemLoader(str(PACKAGE_DIR / "templates")),
    autoescape=select_autoescape(),
)
templates = Jinja2Templates(env=_template_env)
router = APIRouter()


def _base_ctx(
    request: Request,
    ctx: AppContext,
    *,
    current_user: User | None = None,
    can_manage_users: bool | None = None,
    can_manage_roles: bool | None = None,
    can_manage_settings: bool | None = None,
) -> dict:
    caps = caps_dict(request)
    if can_manage_users is not None:
        caps["can_manage_users"] = can_manage_users
    if can_manage_roles is not None:
        caps["can_manage_roles"] = can_manage_roles
    if can_manage_settings is not None:
        caps["can_manage_settings"] = can_manage_settings
    return {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "auth_user": current_user or getattr(request.state, "auth_user", None),
        "agent_token": getattr(request.state, "agent_token", "") or "",
        **caps,
        "creo_label": "—",
        "creo_open_name": "",
        "creo_open_title": "",
        "creo_open_mode": "association",
        "agent_base_url": ctx.settings.ui.agent_base_url,
        "workspace_poll_interval_ms": ctx.settings.ui.workspace_poll_interval_ms,
    }


def _login_session(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.uuid
    set_request_identity(
        UserIdentity(
            user_name=user.username,
            machine_name="web",
            user_uuid=user.uuid,
            display_name=user.display_name,
        )
    )


def _clear_session(request: Request) -> None:
    request.session.clear()
    set_request_identity(None)


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    if not ctx.auth_enabled:
        return RedirectResponse("/", status_code=303)
    ctx.user_accounts.ensure_builtin_roles(db)
    if not ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth_setup.html",
        {**_base_ctx(request, ctx), "error": None, "username": "admin"},
    )


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    display_name: str = Form(""),
    username: str = Form("admin"),
    password: str = Form(""),
    password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    ctx.user_accounts.ensure_builtin_roles(db)
    if not ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/login", status_code=303)
    error = None
    if password != password_confirm:
        error = "Passwords do not match."
    else:
        try:
            user = ctx.user_accounts.create_first_admin(
                db,
                username=username,
                display_name=display_name,
                password=password,
            )
            db.commit()
            _login_session(request, user)
            return RedirectResponse(
                default_app_path(caps_for_user(ctx.user_accounts, user)),
                status_code=303,
            )
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "auth_setup.html",
        {
            **_base_ctx(request, ctx),
            "error": error,
            "username": username,
            "display_name": display_name,
        },
        status_code=400 if error else 200,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    if not ctx.auth_enabled:
        return RedirectResponse("/", status_code=303)
    if ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/setup", status_code=303)
    user_uuid = request.session.get(SESSION_USER_KEY)
    if user_uuid:
        user = ctx.user_accounts.get_by_uuid(db, str(user_uuid))
        if user is not None:
            return RedirectResponse(
                default_app_path(caps_for_user(ctx.user_accounts, user)),
                status_code=303,
            )
    return templates.TemplateResponse(
        request,
        "auth_login.html",
        {**_base_ctx(request, ctx), "error": None, "next": request.query_params.get("next") or ""},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    if ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/setup", status_code=303)
    try:
        user = ctx.user_accounts.authenticate(db, username, password)
        db.commit()
        _login_session(request, user)
        if user.must_change_password:
            return RedirectResponse("/account/password", status_code=303)
        caps = caps_for_user(ctx.user_accounts, user)
        target = resolve_post_login_target(caps, next)
        return RedirectResponse(target, status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "auth_login.html",
            {
                **_base_ctx(request, ctx),
                "error": exc.message,
                "username": username,
                "next": next,
            },
            status_code=400,
        )


@router.get("/logout")
@router.post("/logout")
def logout(request: Request):
    _clear_session(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/no-access", response_class=HTMLResponse)
def no_access_page(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    """Friendly HTML when the account has neither Files browse nor Administration."""
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    caps = caps_for_user(ctx.user_accounts, user)
    # If they gained access, send them to the right place instead of this page.
    landing = default_app_path(caps)
    if landing != "/no-access":
        return RedirectResponse(landing, status_code=303)
    return templates.TemplateResponse(
        request,
        "auth_no_access.html",
        {
            **_base_ctx(request, ctx, current_user=user),
        },
    )


@router.get("/account/password", response_class=HTMLResponse)
def password_page(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth_password.html",
        {
            **_base_ctx(
                request,
                ctx,
                current_user=user,
                can_manage_users=ctx.user_accounts.can_manage_users(user),
                can_manage_settings=ctx.user_accounts.can_manage_settings(user),
            ),
            "error": None,
            "forced": bool(user.must_change_password),
        },
    )


@router.post("/account/password", response_class=HTMLResponse)
def password_submit(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    error = None
    if new_password != new_password_confirm:
        error = "New passwords do not match."
    else:
        try:
            ctx.user_accounts.change_password(db, user, current_password, new_password)
            db.commit()
            return RedirectResponse(
                default_app_path(caps_for_user(ctx.user_accounts, user)),
                status_code=303,
            )
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "auth_password.html",
        {
            **_base_ctx(
                request,
                ctx,
                current_user=user,
                can_manage_users=ctx.user_accounts.can_manage_users(user),
                can_manage_settings=ctx.user_accounts.can_manage_settings(user),
            ),
            "error": error,
            "forced": bool(user.must_change_password),
        },
        status_code=400,
    )


def _require_admin(request: Request, ctx: AppContext, db: Session) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_manage_users(user):
        return HTMLResponse("<h1>403 Forbidden</h1><p>Administrator access required.</p>", status_code=403)
    return user


def _require_roles_manager(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_manage_roles(user):
        return HTMLResponse("<h1>403 Forbidden</h1><p>Roles management access required.</p>", status_code=403)
    return user


def _require_projects_manager(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_manage_projects(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Project management access required.</p>",
            status_code=403,
        )
    return user


def _require_membership_assign(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_assign_projects(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Project membership access required (projects.assign).</p>",
            status_code=403,
        )
    return user


def _is_blocked(result: User | HTMLResponse | RedirectResponse) -> bool:
    return isinstance(result, (HTMLResponse, RedirectResponse))


def _permission_groups(
    selected: set[str] | None = None, *, lock_administration: bool = False
) -> list[dict]:
    selected = selected or set()
    desc = {key: description for key, description in BUILTIN_PERMISSIONS}
    groups = []
    for title, keys in PERMISSION_GROUPS:
        groups.append(
            {
                "title": title,
                # Use "perms" — Jinja resolves dict.items as the method.
                "perms": [
                    {
                        "key": key,
                        "description": desc.get(key, key),
                        "checked": key in selected,
                        "locked": lock_administration and key in ADMINISTRATION_PERMISSION_KEYS,
                    }
                    for key in keys
                ],
            }
        )
    return groups


def _parse_permission_keys(raw: list[str] | None) -> list[str]:
    known = {key for key, _ in BUILTIN_PERMISSIONS}
    return [key for key in (raw or []) if key in known]


def _parse_project_access(
    *,
    project_access_present: str | None,
    access_all_projects: str | None,
    project_uuid: list[str] | None,
) -> tuple[bool, list[str]]:
    """Return (access_all, project_uuids). Legacy posts without the field keep All projects."""
    if not project_access_present:
        return True, []
    access_all = (access_all_projects or "").strip().lower() in {"1", "on", "true", "yes"}
    if isinstance(project_uuid, str):
        uuids = [project_uuid.strip()] if project_uuid.strip() else []
    else:
        uuids = [str(v).strip() for v in (project_uuid or []) if str(v).strip()]
    return access_all, uuids


def _project_access_form(
    ctx: AppContext,
    db: Session,
    *,
    access_all: bool = True,
    selected_uuids: set[str] | None = None,
) -> dict:
    selected = selected_uuids or set()
    projects = [
        {
            "uuid": p.uuid,
            "name": p.name,
            "number": p.number or "",
            "checked": p.uuid in selected,
        }
        for p in ctx.projects.list_projects(db)
    ]
    return {
        "access_all_projects": access_all,
        "project_options": projects,
    }


def _user_form_payload(
    *,
    display_name: str = "",
    username: str = "",
    email: str = "",
    role: str = BuiltinRole.ENGINEER.value,
    status: str = UserStatus.ACTIVE.value,
    uuid: str | None = None,
    access_all_projects: bool = True,
    selected_project_uuids: list[str] | None = None,
) -> dict:
    payload: dict = {
        "display_name": display_name,
        "username": username,
        "email": email,
        "role": role,
        "status": status,
        "access_all_projects": access_all_projects,
        "selected_project_uuids": list(selected_project_uuids or []),
    }
    if uuid is not None:
        payload["uuid"] = uuid
    return payload


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    if not ctx.auth_enabled:
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                **_base_ctx(
                    request,
                    ctx,
                    can_manage_users=False,
                    can_manage_roles=False,
                    can_manage_settings=True,
                ),
            },
        )
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    caps = caps_for_user(ctx.user_accounts, user)
    if not can_open_administration(caps):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Administrator access required.</p>",
            status_code=403,
        )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            **_base_ctx(request, ctx, current_user=user),
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    users = ctx.user_accounts.list_users(db)
    can_roles = ctx.user_accounts.can_manage_roles(admin)
    rows = [
        {
            "uuid": u.uuid,
            "display_name": u.display_name,
            "username": u.username,
            "role": ctx.user_accounts.primary_role_name(u),
            "role_uuid": ctx.user_accounts.primary_role_uuid(u),
            "status": u.status,
            "project_access": (
                "All"
                if getattr(u, "access_all_projects", True)
                else str(len(u.projects or []))
            ),
            "is_full_admin": ctx.user_accounts.is_full_administrator(u),
            "can_edit": ctx.user_accounts.can_edit_user(admin, u),
        }
        for u in users
    ]
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            **_base_ctx(
                request,
                ctx,
                current_user=admin,
                can_manage_users=True,
                can_manage_roles=can_roles,
                can_manage_settings=True,
            ),
            "users": rows,
            "actor_is_full_admin": ctx.user_accounts.is_full_administrator(admin),
        },
    )


def _user_form_admin_flags(ctx: AppContext, admin: User) -> dict:
    return {
        "can_assign_roles": ctx.user_accounts.can_assign_roles(admin),
        "can_assign_projects": ctx.user_accounts.can_assign_projects(admin),
        "can_set_passwords": ctx.user_accounts.can_set_passwords(admin),
    }


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_user_new(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    flags = _user_form_admin_flags(ctx, admin)
    roles = (
        ctx.user_accounts.assignable_roles_for(db, admin) if flags["can_assign_roles"] else []
    )
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True, can_manage_settings=True),
            "error": None,
            "mode": "new",
            "editing_self": False,
            **flags,
            "roles": [{"name": r.name} for r in roles],
            "form": _user_form_payload(),
        },
    )


@router.post("/admin/users/new", response_class=HTMLResponse)
def admin_user_create(
    request: Request,
    display_name: str = Form(""),
    username: str = Form(""),
    email: str = Form(""),
    role: str | None = Form(default=None),
    status: str = Form(UserStatus.ACTIVE.value),
    password: str = Form(""),
    password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    from creopdm.exceptions import PermissionDeniedError

    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    flags = _user_form_admin_flags(ctx, admin)
    roles = (
        ctx.user_accounts.assignable_roles_for(db, admin) if flags["can_assign_roles"] else []
    )
    role_name = (role or "").strip() or BuiltinRole.ENGINEER.value
    error = None
    if password != password_confirm:
        error = "Passwords do not match."
    else:
        try:
            ctx.user_accounts.create_user(
                db,
                username=username,
                display_name=display_name,
                password=password,
                email=email,
                role_name=role_name,
                status=status,
                must_change_password=True,
                access_all_projects=True,
                actor=admin,
            )
            db.commit()
            return RedirectResponse("/admin/users", status_code=303)
        except PermissionDeniedError as exc:
            db.rollback()
            return HTMLResponse(
                f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
                status_code=403,
            )
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True, can_manage_settings=True),
            "error": error,
            "mode": "new",
            "editing_self": False,
            **flags,
            "roles": [{"name": r.name} for r in roles],
            "form": _user_form_payload(
                display_name=display_name,
                username=username,
                email=email,
                role=role_name,
                status=status,
            ),
        },
        status_code=400,
    )


@router.get("/admin/users/{user_uuid}", response_class=HTMLResponse)
def admin_user_detail(
    user_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    user = ctx.user_accounts.get_by_uuid(db, user_uuid)
    if user is None:
        return RedirectResponse("/admin/users", status_code=303)
    try:
        ctx.user_accounts.ensure_can_edit_user(admin, user)
    except CreoPDMError as exc:
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
            status_code=403,
        )
    flags = _user_form_admin_flags(ctx, admin)
    roles = (
        ctx.user_accounts.assignable_roles_for(db, admin) if flags["can_assign_roles"] else []
    )
    if flags["can_assign_roles"] and not any(
        r.name == ctx.user_accounts.primary_role_name(user) for r in roles
    ):
        current = ctx.user_accounts.role_by_name(db, ctx.user_accounts.primary_role_name(user))
        if current is not None:
            roles = list(roles) + [current]
    editing_self = admin.id == user.id
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True, can_manage_settings=True),
            "error": None,
            "mode": "edit",
            "editing_self": editing_self,
            **flags,
            "roles": [{"name": r.name} for r in roles],
            "form": _user_form_payload(
                uuid=user.uuid,
                display_name=user.display_name,
                username=user.username,
                email=user.email or "",
                role=ctx.user_accounts.primary_role_name(user),
                status=user.status,
            ),
        },
    )


@router.post("/admin/users/{user_uuid}", response_class=HTMLResponse)
def admin_user_update(
    user_uuid: str,
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    role: str | None = Form(default=None),
    status: str = Form(UserStatus.ACTIVE.value),
    password: str = Form(""),
    password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    from creopdm.exceptions import PermissionDeniedError

    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    user = ctx.user_accounts.get_by_uuid(db, user_uuid)
    if user is None:
        return RedirectResponse("/admin/users", status_code=303)
    try:
        ctx.user_accounts.ensure_can_edit_user(admin, user)
    except CreoPDMError as exc:
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
            status_code=403,
        )
    editing_self = admin.id == user.id
    flags = _user_form_admin_flags(ctx, admin)
    roles = (
        ctx.user_accounts.assignable_roles_for(db, admin) if flags["can_assign_roles"] else []
    )
    error = None
    if password and password != password_confirm:
        error = "Passwords do not match."
    elif editing_self and status != user.status:
        error = "You cannot change your own status. Ask another administrator."
    elif (
        editing_self
        and role is not None
        and str(role).strip()
        and str(role).strip() != ctx.user_accounts.primary_role_name(user)
    ):
        error = "You cannot change your own role. Ask another administrator."
    else:
        try:
            kwargs: dict = {
                "display_name": display_name,
                "email": email,
                "actor": admin,
            }
            if not editing_self:
                kwargs["status"] = status
            if (
                not editing_self
                and role is not None
                and str(role).strip()
            ):
                kwargs["role_name"] = str(role).strip()
            if password:
                kwargs["password"] = password
                kwargs["must_change_password"] = True
            ctx.user_accounts.update_user(db, user_uuid, **kwargs)
            db.commit()
            return RedirectResponse("/admin/users", status_code=303)
        except PermissionDeniedError as exc:
            db.rollback()
            return HTMLResponse(
                f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
                status_code=403,
            )
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True, can_manage_settings=True),
            "error": error,
            "mode": "edit",
            "editing_self": editing_self,
            **flags,
            "roles": [{"name": r.name} for r in roles],
            "form": _user_form_payload(
                uuid=user_uuid,
                display_name=display_name,
                username=user.username,
                email=email,
                role=(
                    str(role).strip()
                    if role is not None and str(role).strip()
                    else ctx.user_accounts.primary_role_name(user)
                ),
                status=status if not editing_self else user.status,
            ),
        },
        status_code=400,
    )


@router.get("/admin/membership", response_class=HTMLResponse)
def admin_membership_home(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    users = [
        u
        for u in ctx.user_accounts.list_users(db)
        if u.status == UserStatus.ACTIVE.value
    ]
    all_projects_count = sum(1 for u in users if getattr(u, "access_all_projects", True))
    restricted = [u for u in users if not getattr(u, "access_all_projects", True)]
    project_rows = []
    for p in ctx.projects.list_projects(db):
        member_count = sum(1 for u in restricted if any(mp.id == p.id for mp in (u.projects or [])))
        project_rows.append(
            {
                "uuid": p.uuid,
                "name": p.name,
                "number": p.number or "",
                "member_count": member_count,
                "can_open_count": member_count + all_projects_count,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin_membership.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "projects": project_rows,
            "all_projects_count": all_projects_count,
        },
    )


@router.get("/admin/membership/projects", response_class=HTMLResponse)
def admin_membership_projects_list(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    users = [
        u
        for u in ctx.user_accounts.list_users(db)
        if u.status == UserStatus.ACTIVE.value
    ]
    all_projects_count = sum(1 for u in users if getattr(u, "access_all_projects", True))
    restricted = [u for u in users if not getattr(u, "access_all_projects", True)]
    projects = []
    for p in ctx.projects.list_projects(db):
        member_count = sum(1 for u in restricted if any(mp.id == p.id for mp in (u.projects or [])))
        projects.append(
            {
                "uuid": p.uuid,
                "name": p.name,
                "number": p.number or "",
                "member_count": member_count,
                "can_open_count": member_count + all_projects_count,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin_membership_projects.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "projects": projects,
            "all_projects_count": all_projects_count,
        },
    )


@router.get("/admin/membership/users", response_class=HTMLResponse)
def admin_membership_users_list(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    users = []
    for u in ctx.user_accounts.list_users(db):
        if u.status != UserStatus.ACTIVE.value:
            continue
        access_all = bool(getattr(u, "access_all_projects", True))
        users.append(
            {
                "uuid": u.uuid,
                "display_name": u.display_name,
                "username": u.username,
                "access_all": access_all,
                "member_count": 0 if access_all else len(u.projects or []),
            }
        )
    return templates.TemplateResponse(
        request,
        "admin_membership_users.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "users": users,
        },
    )


@router.get("/admin/membership/users/{user_uuid}", response_class=HTMLResponse)
def admin_membership_user_detail(
    user_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    user = ctx.user_accounts.get_by_uuid(db, user_uuid)
    if user is None:
        return RedirectResponse("/admin/membership/users", status_code=303)
    access_all = bool(user.access_all_projects)
    selected = {p.uuid for p in (user.projects or [])}
    access = _project_access_form(ctx, db, access_all=access_all, selected_uuids=selected)
    return templates.TemplateResponse(
        request,
        "admin_membership_user.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "form": {
                "uuid": user.uuid,
                "display_name": user.display_name,
                "username": user.username,
                "role": ctx.user_accounts.primary_role_name(user),
            },
            **access,
        },
    )


@router.post("/admin/membership/users/{user_uuid}", response_class=HTMLResponse)
def admin_membership_user_save(
    user_uuid: str,
    request: Request,
    project_access_present: str | None = Form(default=None),
    access_all_projects: str | None = Form(default=None),
    project_uuid: list[str] = Form(default=[]),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    from creopdm.exceptions import PermissionDeniedError

    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    user = ctx.user_accounts.get_by_uuid(db, user_uuid)
    if user is None:
        return RedirectResponse("/admin/membership/users", status_code=303)
    access_all, project_uuids = _parse_project_access(
        project_access_present=project_access_present or "1",
        access_all_projects=access_all_projects,
        project_uuid=project_uuid,
    )
    error = None
    try:
        ctx.user_accounts.ensure_can_assign_projects(manager)
        ctx.user_accounts.set_project_access(
            db,
            user,
            access_all=access_all,
            project_uuids=project_uuids if not access_all else None,
        )
        db.commit()
        return RedirectResponse("/admin/membership/users", status_code=303)
    except PermissionDeniedError as exc:
        db.rollback()
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
            status_code=403,
        )
    except CreoPDMError as exc:
        db.rollback()
        error = exc.message
    access = _project_access_form(
        ctx, db, access_all=access_all, selected_uuids=set(project_uuids)
    )
    return templates.TemplateResponse(
        request,
        "admin_membership_user.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": error,
            "form": {
                "uuid": user.uuid,
                "display_name": user.display_name,
                "username": user.username,
                "role": ctx.user_accounts.primary_role_name(user),
            },
            **access,
        },
        status_code=400,
    )


@router.get("/admin/membership/projects/{project_uuid}", response_class=HTMLResponse)
def admin_membership_project_detail(
    project_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        project = ctx.projects.get_project(db, project_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/membership/projects", status_code=303)
    all_projects_users = []
    restricted_users = []
    for u in ctx.user_accounts.list_users(db):
        if u.status != UserStatus.ACTIVE.value:
            continue
        row = {
            "uuid": u.uuid,
            "display_name": u.display_name,
            "username": u.username,
        }
        if getattr(u, "access_all_projects", True):
            all_projects_users.append(row)
        else:
            member_ids = {p.id for p in (u.projects or [])}
            restricted_users.append({**row, "member": project.id in member_ids})
    return templates.TemplateResponse(
        request,
        "admin_membership_project.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "project": {
                "uuid": project.uuid,
                "name": project.name,
                "number": project.number or "",
            },
            "all_projects_users": all_projects_users,
            "restricted_users": restricted_users,
        },
    )


@router.post("/admin/membership/projects/{project_uuid}", response_class=HTMLResponse)
def admin_membership_project_save(
    project_uuid: str,
    request: Request,
    member_uuid: list[str] = Form(default=[]),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    from creopdm.exceptions import PermissionDeniedError

    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        project = ctx.projects.get_project(db, project_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/membership/projects", status_code=303)
    if isinstance(member_uuid, str):
        members = [member_uuid.strip()] if member_uuid.strip() else []
    else:
        members = [str(v).strip() for v in (member_uuid or []) if str(v).strip()]
    error = None
    try:
        ctx.user_accounts.set_restricted_project_members(
            db, project, member_user_uuids=members, actor=manager
        )
        db.commit()
        return RedirectResponse("/admin/membership/projects", status_code=303)
    except PermissionDeniedError as exc:
        db.rollback()
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
            status_code=403,
        )
    except CreoPDMError as exc:
        db.rollback()
        error = exc.message
    all_projects_users = []
    restricted_users = []
    wanted = set(members)
    for u in ctx.user_accounts.list_users(db):
        if u.status != UserStatus.ACTIVE.value:
            continue
        row = {
            "uuid": u.uuid,
            "display_name": u.display_name,
            "username": u.username,
        }
        if getattr(u, "access_all_projects", True):
            all_projects_users.append(row)
        else:
            restricted_users.append({**row, "member": u.uuid in wanted})
    return templates.TemplateResponse(
        request,
        "admin_membership_project.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": error,
            "project": {
                "uuid": project.uuid,
                "name": project.name,
                "number": project.number or "",
            },
            "all_projects_users": all_projects_users,
            "restricted_users": restricted_users,
        },
        status_code=400,
    )


@router.get("/admin/roles", response_class=HTMLResponse)
def admin_roles(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    roles = ctx.user_accounts.list_roles(db)
    rows = [
        {
            "uuid": r.uuid,
            "name": r.name,
            "description": r.description or "",
            "user_count": len(r.users),
            "permission_count": len(r.permissions),
        }
        for r in roles
    ]
    return templates.TemplateResponse(
        request,
        "admin_roles.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "roles": rows,
        },
    )


@router.get("/admin/roles/new", response_class=HTMLResponse)
def admin_role_new(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return templates.TemplateResponse(
        request,
        "admin_role_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "new",
            "editing_own_role": False,
            "permission_groups": _permission_groups(),
            "form": {"name": "", "description": ""},
            "can_delete": False,
        },
    )


@router.post("/admin/roles/new", response_class=HTMLResponse)
def admin_role_create(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    permission: list[str] = Form(default=[]),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    permission_keys = _parse_permission_keys([str(v) for v in permission])
    error = None
    try:
        ctx.user_accounts.create_role(
            db,
            name=name,
            description=description,
            permission_keys=permission_keys,
        )
        db.commit()
        return RedirectResponse("/admin/roles", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        error = exc.message
    return templates.TemplateResponse(
        request,
        "admin_role_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": error,
            "mode": "new",
            "editing_own_role": False,
            "permission_groups": _permission_groups(set(permission_keys)),
            "form": {"name": name, "description": description},
            "can_delete": False,
        },
        status_code=400,
    )


@router.get("/admin/roles/{role_uuid}", response_class=HTMLResponse)
def admin_role_detail(
    role_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    role = ctx.user_accounts.get_role_by_uuid(db, role_uuid)
    if role is None:
        return RedirectResponse("/admin/roles", status_code=303)
    selected = {p.key for p in role.permissions}
    editing_own = ctx.user_accounts.user_holds_role(manager, role)
    return templates.TemplateResponse(
        request,
        "admin_role_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "edit",
            "editing_own_role": editing_own,
            "permission_groups": _permission_groups(
                selected, lock_administration=editing_own
            ),
            "form": {
                "uuid": role.uuid,
                "name": role.name,
                "description": role.description or "",
            },
            "can_delete": (not editing_own) and len(role.users) == 0,
            "user_count": len(role.users),
        },
    )


@router.post("/admin/roles/{role_uuid}", response_class=HTMLResponse)
def admin_role_update(
    role_uuid: str,
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    permission: list[str] = Form(default=[]),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    role = ctx.user_accounts.get_role_by_uuid(db, role_uuid)
    if role is None:
        return RedirectResponse("/admin/roles", status_code=303)
    permission_keys = _parse_permission_keys([str(v) for v in permission])
    editing_own = ctx.user_accounts.user_holds_role(manager, role)
    error = None
    try:
        ctx.user_accounts.update_role(
            db,
            role_uuid,
            name=name,
            description=description,
            permission_keys=permission_keys,
            actor=manager,
        )
        db.commit()
        return RedirectResponse("/admin/roles", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        error = exc.message
    role = ctx.user_accounts.get_role_by_uuid(db, role_uuid) or role
    editing_own = ctx.user_accounts.user_holds_role(manager, role)
    return templates.TemplateResponse(
        request,
        "admin_role_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": error,
            "mode": "edit",
            "editing_own_role": editing_own,
            "permission_groups": _permission_groups(
                set(permission_keys), lock_administration=editing_own
            ),
            "form": {
                "uuid": role_uuid,
                "name": name,
                "description": description,
            },
            "can_delete": (not editing_own) and len(role.users) == 0,
            "user_count": len(role.users),
        },
        status_code=400,
    )


@router.post("/admin/roles/{role_uuid}/delete", response_class=HTMLResponse)
def admin_role_delete(
    role_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_roles_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        ctx.user_accounts.delete_role(db, role_uuid, actor=manager)
        db.commit()
        return RedirectResponse("/admin/roles", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        role = ctx.user_accounts.get_role_by_uuid(db, role_uuid)
        if role is None:
            return RedirectResponse("/admin/roles", status_code=303)
        editing_own = ctx.user_accounts.user_holds_role(manager, role)
        selected = {p.key for p in role.permissions}
        return templates.TemplateResponse(
            request,
            "admin_role_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": exc.message,
                "mode": "edit",
                "editing_own_role": editing_own,
                "permission_groups": _permission_groups(
                    selected, lock_administration=editing_own
                ),
                "form": {
                    "uuid": role.uuid,
                    "name": role.name,
                    "description": role.description or "",
                },
                "can_delete": (not editing_own) and len(role.users) == 0,
                "user_count": len(role.users),
            },
            status_code=400,
        )


def _project_form(
    *,
    name: str = "",
    number: str = "",
    description: str = "",
    vault_folder: str = "",
    uuid: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "number": number,
        "description": description,
        "vault_folder": vault_folder,
    }
    if uuid is not None:
        payload["uuid"] = uuid
    return payload


@router.get("/admin/projects", response_class=HTMLResponse)
def admin_projects(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    projects = [project_to_response(p) for p in ctx.projects.list_projects(db)]
    return templates.TemplateResponse(
        request,
        "admin_projects.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "projects": projects,
        },
    )


@router.get("/admin/projects/new", response_class=HTMLResponse)
def admin_project_new(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return templates.TemplateResponse(
        request,
        "admin_project_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "new",
            "form": _project_form(),
            "delete_error": None,
        },
    )


@router.post("/admin/projects/new", response_class=HTMLResponse)
def admin_project_create(
    request: Request,
    name: str = Form(...),
    number: str = Form(""),
    description: str = Form(""),
    vault_folder: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    form = _project_form(
        name=name,
        number=number,
        description=description,
        vault_folder=vault_folder,
    )
    try:
        project = ctx.projects.create_project(
            db,
            name=name,
            number=number or None,
            description=description or None,
            vault_folder=(vault_folder or "").strip() or None,
        )
        ctx.user_accounts.grant_project_access(db, manager, project)
        db.commit()
        return RedirectResponse("/admin/projects", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_project_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": exc.message,
                "mode": "new",
                "form": form,
                "delete_error": None,
            },
            status_code=400,
        )


@router.get("/admin/projects/{project_uuid}", response_class=HTMLResponse)
def admin_project_detail(
    project_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        project = ctx.projects.get_project(db, project_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/projects", status_code=303)
    payload = project_to_response(project)
    return templates.TemplateResponse(
        request,
        "admin_project_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "edit",
            "form": _project_form(
                name=payload.name,
                number=payload.number or "",
                description=payload.description or "",
                vault_folder=payload.vault_folder,
                uuid=payload.uuid,
            ),
            "delete_error": None,
        },
    )


@router.post("/admin/projects/{project_uuid}", response_class=HTMLResponse)
def admin_project_update(
    project_uuid: str,
    request: Request,
    name: str = Form(...),
    number: str = Form(""),
    description: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        project = ctx.projects.get_project(db, project_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/projects", status_code=303)
    form = _project_form(
        name=name,
        number=number,
        description=description,
        vault_folder=project.vault_folder or project.uuid,
        uuid=project.uuid,
    )
    try:
        ctx.projects.update_project(
            db,
            project_uuid,
            name=name,
            number=number or None,
            description=description or None,
        )
        db.commit()
        return RedirectResponse("/admin/projects", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_project_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": exc.message,
                "mode": "edit",
                "form": form,
                "delete_error": None,
            },
            status_code=400,
        )


@router.post("/admin/projects/{project_uuid}/delete", response_class=HTMLResponse)
def admin_project_delete(
    project_uuid: str,
    request: Request,
    confirm_name: str = Form(...),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_projects_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        project = ctx.projects.get_project(db, project_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/projects", status_code=303)
    payload = project_to_response(project)
    form = _project_form(
        name=payload.name,
        number=payload.number or "",
        description=payload.description or "",
        vault_folder=payload.vault_folder,
        uuid=payload.uuid,
    )
    if (confirm_name or "").strip() != project.name:
        return templates.TemplateResponse(
            request,
            "admin_project_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": None,
                "mode": "edit",
                "form": form,
                "delete_error": "Type the exact project name to confirm removal.",
            },
            status_code=400,
        )
    try:
        ctx.projects.delete_project(db, project_uuid)
        db.commit()
        return RedirectResponse("/admin/projects", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_project_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": None,
                "mode": "edit",
                "form": form,
                "delete_error": exc.message,
            },
            status_code=400,
        )
