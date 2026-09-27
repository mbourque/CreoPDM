"""HTML + form endpoints for setup, login, logout, password, and user admin."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.auth_constants import BuiltinRole, UserStatus
from creopdm.auth_session import SESSION_USER_KEY
from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.context import AppContext
from creopdm.exceptions import CreoPDMError
from creopdm.models.user import User
from creopdm.utils.identity import UserIdentity, set_request_identity

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
    can_manage_users: bool = False,
) -> dict:
    return {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "auth_user": current_user,
        "can_manage_users": can_manage_users,
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
            return RedirectResponse("/", status_code=303)
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
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse("/", status_code=303)
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
        target = next.strip() if next and next.startswith("/") and not next.startswith("//") else "/"
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
            **_base_ctx(request, ctx, current_user=user, can_manage_users=ctx.user_accounts.can_manage_users(user)),
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
            return RedirectResponse("/", status_code=303)
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "auth_password.html",
        {
            **_base_ctx(request, ctx, current_user=user, can_manage_users=ctx.user_accounts.can_manage_users(user)),
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


def _is_blocked(result: User | HTMLResponse | RedirectResponse) -> bool:
    return isinstance(result, (HTMLResponse, RedirectResponse))


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    users = ctx.user_accounts.list_users(db)
    rows = [
        {
            "uuid": u.uuid,
            "display_name": u.display_name,
            "username": u.username,
            "role": ctx.user_accounts.primary_role_name(u),
            "status": u.status,
        }
        for u in users
    ]
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True),
            "users": rows,
        },
    )


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_user_new(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    roles = ctx.user_accounts.list_roles(db)
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True),
            "error": None,
            "mode": "new",
            "roles": [{"name": r.name} for r in roles],
            "form": {
                "display_name": "",
                "username": "",
                "email": "",
                "role": BuiltinRole.ENGINEER.value,
                "status": UserStatus.ACTIVE.value,
            },
        },
    )


@router.post("/admin/users/new", response_class=HTMLResponse)
def admin_user_create(
    request: Request,
    display_name: str = Form(""),
    username: str = Form(""),
    email: str = Form(""),
    role: str = Form(BuiltinRole.ENGINEER.value),
    status: str = Form(UserStatus.ACTIVE.value),
    password: str = Form(""),
    password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    roles = ctx.user_accounts.list_roles(db)
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
                role_name=role,
                status=status,
                must_change_password=True,
            )
            db.commit()
            return RedirectResponse("/admin/users", status_code=303)
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True),
            "error": error,
            "mode": "new",
            "roles": [{"name": r.name} for r in roles],
            "form": {
                "display_name": display_name,
                "username": username,
                "email": email,
                "role": role,
                "status": status,
            },
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
    roles = ctx.user_accounts.list_roles(db)
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True),
            "error": None,
            "mode": "edit",
            "roles": [{"name": r.name} for r in roles],
            "form": {
                "uuid": user.uuid,
                "display_name": user.display_name,
                "username": user.username,
                "email": user.email or "",
                "role": ctx.user_accounts.primary_role_name(user),
                "status": user.status,
            },
        },
    )


@router.post("/admin/users/{user_uuid}", response_class=HTMLResponse)
def admin_user_update(
    user_uuid: str,
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    role: str = Form(BuiltinRole.ENGINEER.value),
    status: str = Form(UserStatus.ACTIVE.value),
    password: str = Form(""),
    password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, ctx, db)
    if _is_blocked(admin):
        return admin
    user = ctx.user_accounts.get_by_uuid(db, user_uuid)
    if user is None:
        return RedirectResponse("/admin/users", status_code=303)
    roles = ctx.user_accounts.list_roles(db)
    error = None
    if password and password != password_confirm:
        error = "Passwords do not match."
    else:
        try:
            kwargs: dict = {
                "display_name": display_name,
                "email": email,
                "role_name": role,
                "status": status,
            }
            if password:
                kwargs["password"] = password
                kwargs["must_change_password"] = True
            ctx.user_accounts.update_user(db, user_uuid, **kwargs)
            db.commit()
            return RedirectResponse(f"/admin/users/{user_uuid}", status_code=303)
        except CreoPDMError as exc:
            db.rollback()
            error = exc.message
    return templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_base_ctx(request, ctx, current_user=admin, can_manage_users=True),
            "error": error,
            "mode": "edit",
            "roles": [{"name": r.name} for r in roles],
            "form": {
                "uuid": user_uuid,
                "display_name": display_name,
                "username": user.username,
                "email": email,
                "role": role,
                "status": status,
            },
        },
        status_code=400,
    )
