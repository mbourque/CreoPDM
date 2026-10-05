"""HTML + form endpoints for setup, login, logout, password, and user admin."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import product_to_response
from creopdm.auth_constants import (
    ADMINISTRATION_PERMISSION_KEYS,
    BUILTIN_PERMISSIONS,
    PERMISSION_GROUPS,
    StarterRole,
    UserStatus,
)
from creopdm.auth_session import (
    SESSION_FORGOT_TOKEN_KEY,
    SESSION_FORGOT_USERNAME_KEY,
    SESSION_USER_KEY,
)
from creopdm.constants import (
    APP_NAME,
    APP_VERSION,
    PRODUCT_STATE_LABELS,
    ActivityAction,
    ProductState,
)
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
from creopdm.utils.passwords import verify_password
from creopdm.utils.timefmt import format_local, format_local_pretty

# Back-compat for default form role.
BuiltinRole = StarterRole

PACKAGE_DIR = Path(__file__).resolve().parent.parent
_template_env = Environment(
    loader=FileSystemLoader(str(PACKAGE_DIR / "templates")),
    autoescape=select_autoescape(),
)
_template_env.filters["local_time"] = format_local
_template_env.filters["local_time_pretty"] = format_local_pretty
_template_env.globals["local_time"] = format_local
_template_env.globals["local_time_pretty"] = format_local_pretty
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
    from creopdm.api.pages import _creo_page
    from creopdm.site_availability import site_is_unavailable, site_unavailable_message

    # Same Creo pill fields as Files — do not paint "Creo: —" on Admin/Utilities
    # (admins without products.view land here first; JS promotes to Connected in Creo).
    return {
        "request": request,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "auth_user": current_user or getattr(request.state, "auth_user", None),
        "agent_token": getattr(request.state, "agent_token", "") or "",
        **caps,
        **_creo_page(ctx),
        "site_unavailable": site_is_unavailable(ctx.settings),
        "site_unavailable_message": site_unavailable_message(ctx.settings),
    }


def _login_session(request: Request, user: User) -> None:
    _clear_forgot_password_grant(request)
    request.session[SESSION_USER_KEY] = user.uuid
    set_request_identity(
        UserIdentity(
            user_name=user.username,
            machine_name="web",
            user_uuid=user.uuid,
            display_name=user.display_name,
        )
    )


def _audit_actor(ctx: AppContext) -> UserIdentity:
    """Session identity for audit rows (falls back only when auth is off)."""
    return ctx.users.get_current_user()


def _clear_session(request: Request) -> None:
    request.session.clear()
    set_request_identity(None)


def _normalize_login_username(username: str) -> str:
    return (username or "").strip().casefold()


def _grant_forgot_password(request: Request, username: str) -> str:
    """Allow forgot-password POST only after wrong password; return one-time form token."""
    token = secrets.token_urlsafe(32)
    request.session[SESSION_FORGOT_USERNAME_KEY] = _normalize_login_username(username)
    request.session[SESSION_FORGOT_TOKEN_KEY] = token
    return token


def _clear_forgot_password_grant(request: Request) -> None:
    request.session.pop(SESSION_FORGOT_USERNAME_KEY, None)
    request.session.pop(SESSION_FORGOT_TOKEN_KEY, None)


def _forgot_password_granted_username(request: Request) -> str | None:
    raw = request.session.get(SESSION_FORGOT_USERNAME_KEY)
    if not isinstance(raw, str):
        return None
    value = _normalize_login_username(raw)
    return value or None


def _forgot_password_grant_token(request: Request) -> str | None:
    raw = request.session.get(SESSION_FORGOT_TOKEN_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _forgot_password_grant_ok(
    request: Request, *, username: str, token: str
) -> bool:
    """True only when username + opaque token match the wrong-password grant."""
    granted = _forgot_password_granted_username(request)
    expected = _forgot_password_grant_token(request)
    submitted = _normalize_login_username(username)
    if not granted or not expected or not submitted or not (token or "").strip():
        return False
    if submitted != granted:
        return False
    return secrets.compare_digest(expected, (token or "").strip())


_FORGOT_LOGIN_HINT = (
    "Sign in with your username first. Forgot password is only available "
    "after a wrong password for that account."
)


def _forgot_password_redirect_to_login() -> RedirectResponse:
    return RedirectResponse(
        "/login?info=" + quote(_FORGOT_LOGIN_HINT),
        status_code=303,
    )


def _forgot_password_form(
    request: Request,
    ctx: AppContext,
    *,
    username: str,
    forgot_token: str,
    email: str = "",
    error: str | None = None,
    info: str | None = None,
    submitted: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth_forgot_password.html",
        {
            **_base_ctx(request, ctx),
            "error": error,
            "info": info,
            "username": username,
            "forgot_token": forgot_token,
            "email": email,
            "submitted": submitted,
        },
        status_code=status_code,
    )


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
        {**_base_ctx(request, ctx), "error": None, "username": "admin", "email": ""},
    )


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    display_name: str = Form(""),
    username: str = Form("admin"),
    email: str = Form(""),
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
                email=email,
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
            "email": email,
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
    # Fresh sign-in page: do not keep a stale forgot-password grant.
    _clear_forgot_password_grant(request)
    return templates.TemplateResponse(
        request,
        "auth_login.html",
        {
            **_base_ctx(request, ctx),
            "error": None,
            "info": request.query_params.get("info") or "",
            "next": request.query_params.get("next") or "",
            "show_forgot": False,
        },
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
        # Forgot password only after wrong password for an *active* known user
        # (not unknown, disabled, empty fields, or other validation failures).
        known = ctx.user_accounts.get_by_username(db, username)
        show_forgot = bool(
            known is not None
            and known.status == UserStatus.ACTIVE.value
            and (password or "")
            and not verify_password(password, known.password_hash)
        )
        if show_forgot:
            forgot_token = _grant_forgot_password(request, known.username)
        else:
            _clear_forgot_password_grant(request)
            forgot_token = ""
        return templates.TemplateResponse(
            request,
            "auth_login.html",
            {
                **_base_ctx(request, ctx),
                "error": exc.message,
                "info": "",
                "username": username,
                "next": next,
                "show_forgot": show_forgot,
                "forgot_token": forgot_token,
            },
            status_code=400,
        )


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, ctx: AppContext = Depends(get_context)):
    """GET is never allowed — typing /forgot-password must not open the form."""
    if not ctx.auth_enabled:
        return RedirectResponse("/", status_code=303)
    return _forgot_password_redirect_to_login()


@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_submit(
    request: Request,
    username: str = Form(""),
    email: str = Form(""),
    forgot_token: str = Form(""),
    forgot_start: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    if ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/setup", status_code=303)
    if not _forgot_password_grant_ok(request, username=username, token=forgot_token):
        _clear_forgot_password_grant(request)
        return _forgot_password_redirect_to_login()
    user = ctx.user_accounts.get_by_username(db, _normalize_login_username(username))
    if user is None or user.status != UserStatus.ACTIVE.value:
        _clear_forgot_password_grant(request)
        return _forgot_password_redirect_to_login()
    uname = user.username
    token = _forgot_password_grant_token(request) or ""

    # Login-form "Forgot password?" button: return the email form (never via GET).
    if forgot_start or not (email or "").strip():
        return _forgot_password_form(
            request,
            ctx,
            username=uname,
            forgot_token=token,
        )

    try:
        result = ctx.password_resets.request_reset(
            db,
            username=uname,
            email=email,
            base_url=str(request.base_url),
            request_ip=request.client.host if request.client else None,
            email_enabled=bool(ctx.settings.email.enabled),
        )
        db.commit()
        # One email try per grant — match or miss — so addresses cannot be probed.
        _clear_forgot_password_grant(request)
        return _forgot_password_form(
            request,
            ctx,
            username=uname,
            forgot_token="",
            email=email,
            info=result.message,
            submitted=True,
        )
    except CreoPDMError as exc:
        # Invalid format only (e.g. blank email). Keep attempt rows if any were written.
        db.commit()
        _clear_forgot_password_grant(request)
        return _forgot_password_form(
            request,
            ctx,
            username=uname,
            forgot_token="",
            email=email,
            error=exc.message,
            submitted=True,
            status_code=400,
        )


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(
    request: Request,
    token: str = Query(""),
    username: str = Query(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    if not ctx.auth_enabled:
        return RedirectResponse("/", status_code=303)
    if ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/setup", status_code=303)
    user = ctx.password_resets.peek_token(db, token)
    uname = (username or "").strip()
    if user is None or not uname or user.username.lower() != uname.lower():
        return templates.TemplateResponse(
            request,
            "auth_reset_password.html",
            {
                **_base_ctx(request, ctx),
                "invalid": True,
                "error": "This reset link is invalid or has expired. Request a new one from the sign-in page.",
                "token": "",
                "username": "",
            },
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "auth_reset_password.html",
        {
            **_base_ctx(request, ctx),
            "invalid": False,
            "error": None,
            "token": token,
            "username": user.username,
        },
    )


@router.post("/reset-password", response_class=HTMLResponse)
def reset_password_submit(
    request: Request,
    token: str = Form(""),
    username: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    if ctx.user_accounts.needs_setup(db):
        return RedirectResponse("/setup", status_code=303)
    uname = (username or "").strip()

    def _reset_error(message: str, *, status: int = 400) -> HTMLResponse:
        user = ctx.password_resets.peek_token(db, token)
        ok_user = (
            user is not None
            and uname
            and user.username.lower() == uname.lower()
        )
        return templates.TemplateResponse(
            request,
            "auth_reset_password.html",
            {
                **_base_ctx(request, ctx),
                "invalid": not ok_user,
                "error": message,
                "token": token if ok_user else "",
                "username": user.username if ok_user else "",
            },
            status_code=status,
        )

    if not uname:
        return _reset_error("Username is required.")
    if (new_password or "") != (new_password_confirm or ""):
        return _reset_error("New password and confirmation do not match.")
    try:
        ctx.password_resets.reset_password(
            db,
            raw_token=token,
            username=uname,
            new_password=new_password,
        )
        db.commit()
        return RedirectResponse(
            "/login?info=" + quote("Password updated. Sign in with your new password."),
            status_code=303,
        )
    except CreoPDMError as exc:
        db.rollback()
        return _reset_error(exc.message)


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


def _require_products_manager(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_manage_products(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Product management access required.</p>",
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
    if not ctx.user_accounts.can_assign_products(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Product membership access required (products.assign).</p>",
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


def _parse_product_access(
    *,
    product_access_present: str | None,
    access_all_products: str | None,
    product_uuid: list[str] | None,
) -> tuple[bool, list[str]]:
    """Return (access_all, product_uuids). Legacy posts without the field keep All products."""
    if not product_access_present:
        return True, []
    access_all = (access_all_products or "").strip().lower() in {"1", "on", "true", "yes"}
    if isinstance(product_uuid, str):
        uuids = [product_uuid.strip()] if product_uuid.strip() else []
    else:
        uuids = [str(v).strip() for v in (product_uuid or []) if str(v).strip()]
    return access_all, uuids


def _product_access_form(
    ctx: AppContext,
    db: Session,
    *,
    access_all: bool = True,
    selected_uuids: set[str] | None = None,
) -> dict:
    selected = selected_uuids or set()
    products = [
        {
            "uuid": p.uuid,
            "name": p.name,
            "number": p.number or "",
            "checked": p.uuid in selected,
        }
        for p in ctx.products.list_products(db, include_archived=True)
    ]
    return {
        "access_all_products": access_all,
        "product_options": products,
    }


def _user_form_payload(
    *,
    display_name: str = "",
    username: str = "",
    email: str = "",
    role: str = BuiltinRole.ENGINEER.value,
    status: str = UserStatus.ACTIVE.value,
    uuid: str | None = None,
    access_all_products: bool = True,
    selected_product_uuids: list[str] | None = None,
) -> dict:
    payload: dict = {
        "display_name": display_name,
        "username": username,
        "email": email,
        "role": role,
        "status": status,
        "access_all_products": access_all_products,
        "selected_product_uuids": list(selected_product_uuids or []),
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
            "product_access": (
                "All"
                if getattr(u, "access_all_products", True)
                else str(len(u.products or []))
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
        "can_assign_products": ctx.user_accounts.can_assign_products(admin),
        "can_set_passwords": ctx.user_accounts.can_set_passwords(admin),
        "actor_is_full_admin": ctx.user_accounts.is_full_administrator(admin),
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
            created = ctx.user_accounts.create_user(
                db,
                username=username,
                display_name=display_name,
                password=password,
                email=email,
                role_name=role_name,
                status=status,
                must_change_password=True,
                access_all_products=False,
                actor=admin,
            )
            ctx.activities.record(
                db,
                ActivityAction.USER_CREATED,
                _audit_actor(ctx),
                details={
                    "username": created.username,
                    "target_user": created.username,
                    "role": ctx.user_accounts.primary_role_name(created),
                    "status": created.status,
                },
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
            old_status = user.status
            old_role = ctx.user_accounts.primary_role_name(user)
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
            updated = ctx.user_accounts.update_user(db, user_uuid, **kwargs)
            actor = _audit_actor(ctx)
            new_status = updated.status
            if new_status != old_status:
                if new_status == UserStatus.DISABLED.value:
                    ctx.activities.record(
                        db,
                        ActivityAction.USER_DISABLED,
                        actor,
                        details={
                            "username": updated.username,
                            "target_user": updated.username,
                            "old_status": old_status,
                            "status": new_status,
                        },
                    )
                elif new_status == UserStatus.ACTIVE.value:
                    ctx.activities.record(
                        db,
                        ActivityAction.USER_ENABLED,
                        actor,
                        details={
                            "username": updated.username,
                            "target_user": updated.username,
                            "old_status": old_status,
                            "status": new_status,
                        },
                    )
            new_role = ctx.user_accounts.primary_role_name(updated)
            if new_role != old_role:
                ctx.activities.record(
                    db,
                    ActivityAction.ROLE_CHANGED,
                    actor,
                    details={
                        "username": updated.username,
                        "target_user": updated.username,
                        "old_role": old_role,
                        "role": new_role,
                    },
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
    all_products_count = sum(1 for u in users if getattr(u, "access_all_products", True))
    restricted = [u for u in users if not getattr(u, "access_all_products", True)]
    product_rows = []
    for p in ctx.products.list_products(db, include_archived=True):
        member_count = sum(1 for u in restricted if any(mp.id == p.id for mp in (u.products or [])))
        product_rows.append(
            {
                "uuid": p.uuid,
                "name": p.name,
                "number": p.number or "",
                "member_count": member_count,
                "can_open_count": member_count + all_products_count,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin_membership.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "products": product_rows,
            "all_products_count": all_products_count,
        },
    )


@router.get("/admin/membership/products", response_class=HTMLResponse)
def admin_membership_products_list(
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
    all_products_count = sum(1 for u in users if getattr(u, "access_all_products", True))
    restricted = [u for u in users if not getattr(u, "access_all_products", True)]
    products = []
    for p in ctx.products.list_products(db, include_archived=True):
        member_count = sum(1 for u in restricted if any(mp.id == p.id for mp in (u.products or [])))
        products.append(
            {
                "uuid": p.uuid,
                "name": p.name,
                "number": p.number or "",
                "member_count": member_count,
                "can_open_count": member_count + all_products_count,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin_membership_products.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "products": products,
            "all_products_count": all_products_count,
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
        access_all = bool(getattr(u, "access_all_products", True))
        users.append(
            {
                "uuid": u.uuid,
                "display_name": u.display_name,
                "username": u.username,
                "access_all": access_all,
                "member_count": 0 if access_all else len(u.products or []),
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
    access_all = bool(user.access_all_products)
    selected = {p.uuid for p in (user.products or [])}
    access = _product_access_form(ctx, db, access_all=access_all, selected_uuids=selected)
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
    product_access_present: str | None = Form(default=None),
    access_all_products: str | None = Form(default=None),
    product_uuid: list[str] = Form(default=[]),
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
    access_all, product_uuids = _parse_product_access(
        product_access_present=product_access_present or "1",
        access_all_products=access_all_products,
        product_uuid=product_uuid,
    )
    error = None
    try:
        ctx.user_accounts.ensure_can_assign_products(manager)
        old_all = bool(getattr(user, "access_all_products", True))
        old_product_uuids = sorted(p.uuid for p in (user.products or []))
        ctx.user_accounts.set_product_access(
            db,
            user,
            access_all=access_all,
            product_uuids=product_uuids if not access_all else None,
        )
        ctx.activities.record(
            db,
            ActivityAction.MEMBERSHIP_CHANGED,
            _audit_actor(ctx),
            details={
                "username": user.username,
                "target_user": user.username,
                "old_access_all_products": old_all,
                "access_all_products": access_all,
                "old_product_uuids": old_product_uuids,
                "product_uuids": [] if access_all else list(product_uuids),
            },
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
    access = _product_access_form(
        ctx, db, access_all=access_all, selected_uuids=set(product_uuids)
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


@router.get("/admin/membership/products/{product_uuid}", response_class=HTMLResponse)
def admin_membership_product_detail(
    product_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_membership_assign(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        product = ctx.products.get_product(db, product_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/membership/products", status_code=303)
    all_products_users = []
    restricted_users = []
    for u in ctx.user_accounts.list_users(db):
        if u.status != UserStatus.ACTIVE.value:
            continue
        row = {
            "uuid": u.uuid,
            "display_name": u.display_name,
            "username": u.username,
        }
        if getattr(u, "access_all_products", True):
            all_products_users.append(row)
        else:
            member_ids = {p.id for p in (u.products or [])}
            restricted_users.append({**row, "member": product.id in member_ids})
    return templates.TemplateResponse(
        request,
        "admin_membership_product.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "product": {
                "uuid": product.uuid,
                "name": product.name,
                "number": product.number or "",
            },
            "all_products_users": all_products_users,
            "restricted_users": restricted_users,
        },
    )


@router.post("/admin/membership/products/{product_uuid}", response_class=HTMLResponse)
def admin_membership_product_save(
    product_uuid: str,
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
        product = ctx.products.get_product(db, product_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/membership/products", status_code=303)
    if isinstance(member_uuid, str):
        members = [member_uuid.strip()] if member_uuid.strip() else []
    else:
        members = [str(v).strip() for v in (member_uuid or []) if str(v).strip()]
    error = None
    try:
        old_members = sorted(
            u.uuid
            for u in ctx.user_accounts.list_users(db)
            if u.status == UserStatus.ACTIVE.value
            and not getattr(u, "access_all_products", True)
            and product.id in {p.id for p in (u.products or [])}
        )
        ctx.user_accounts.set_restricted_product_members(
            db, product, member_user_uuids=members, actor=manager
        )
        ctx.activities.record(
            db,
            ActivityAction.MEMBERSHIP_CHANGED,
            _audit_actor(ctx),
            product_id=product.id,
            details={
                "product": product.name,
                "product_uuid": product.uuid,
                "old_member_uuids": old_members,
                "member_uuids": list(members),
            },
        )
        db.commit()
        return RedirectResponse("/admin/membership/products", status_code=303)
    except PermissionDeniedError as exc:
        db.rollback()
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.message}</p>",
            status_code=403,
        )
    except CreoPDMError as exc:
        db.rollback()
        error = exc.message
    all_products_users = []
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
        if getattr(u, "access_all_products", True):
            all_products_users.append(row)
        else:
            restricted_users.append({**row, "member": u.uuid in wanted})
    return templates.TemplateResponse(
        request,
        "admin_membership_product.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": error,
            "product": {
                "uuid": product.uuid,
                "name": product.name,
                "number": product.number or "",
            },
            "all_products_users": all_products_users,
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
        role = ctx.user_accounts.create_role(
            db,
            name=name,
            description=description,
            permission_keys=permission_keys,
        )
        ctx.activities.record(
            db,
            ActivityAction.ROLE_CHANGED,
            _audit_actor(ctx),
            details={
                "role": role.name,
                "op": "created",
                "permissions": sorted(permission_keys),
            },
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
        old_name = role.name
        old_keys = sorted(p.key for p in role.permissions)
        ctx.user_accounts.update_role(
            db,
            role_uuid,
            name=name,
            description=description,
            permission_keys=permission_keys,
            actor=manager,
        )
        ctx.activities.record(
            db,
            ActivityAction.ROLE_CHANGED,
            _audit_actor(ctx),
            details={
                "role": (name or "").strip() or old_name,
                "old_role": old_name,
                "op": "updated",
                "old_permissions": old_keys,
                "permissions": sorted(permission_keys),
            },
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
        role = ctx.user_accounts.get_role_by_uuid(db, role_uuid)
        role_name = role.name if role is not None else role_uuid
        ctx.user_accounts.delete_role(db, role_uuid, actor=manager)
        ctx.activities.record(
            db,
            ActivityAction.ROLE_CHANGED,
            _audit_actor(ctx),
            details={"role": role_name, "op": "deleted"},
        )
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


def _product_form(
    *,
    name: str = "",
    number: str = "",
    description: str = "",
    vault_folder: str = "",
    state: str = "IN_WORK",
    read_only: bool = False,
    uuid: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "number": number,
        "description": description,
        "vault_folder": vault_folder,
        "state": state or "IN_WORK",
        "read_only": bool(read_only),
    }
    if uuid is not None:
        payload["uuid"] = uuid
    return payload


@router.get("/admin/products", response_class=HTMLResponse)
def admin_products(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    products = [
        product_to_response(p)
        for p in ctx.products.list_products(db, include_inactive=True, include_archived=True)
    ]
    return templates.TemplateResponse(
        request,
        "admin_products.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "products": products,
            "product_state_labels": PRODUCT_STATE_LABELS,
        },
    )


@router.get("/admin/products/new", response_class=HTMLResponse)
def admin_product_new(request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)):
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return templates.TemplateResponse(
        request,
        "admin_product_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "new",
            "form": _product_form(),
            "delete_error": None,
            "product_states": list(ProductState),
            "product_state_labels": PRODUCT_STATE_LABELS,
        },
    )


@router.post("/admin/products/new", response_class=HTMLResponse)
def admin_product_create(
    request: Request,
    name: str = Form(...),
    number: str = Form(""),
    description: str = Form(""),
    vault_folder: str = Form(""),
    state: str = Form("IN_WORK"),
    read_only: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    is_read_only = str(read_only or "").strip().lower() in {"1", "true", "on", "yes"}
    form = _product_form(
        name=name,
        number=number,
        description=description,
        vault_folder=vault_folder,
        state=state,
        read_only=is_read_only,
    )
    try:
        product = ctx.products.create_product(
            db,
            name=name,
            number=number or None,
            description=description or None,
            vault_folder=(vault_folder or "").strip() or None,
            state=state,
            read_only=is_read_only,
        )
        ctx.user_accounts.grant_product_access(db, manager, product)
        db.commit()
        return RedirectResponse("/admin/products", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_product_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": exc.message,
                "mode": "new",
                "form": form,
                "delete_error": None,
                "product_states": list(ProductState),
                "product_state_labels": PRODUCT_STATE_LABELS,
            },
            status_code=400,
        )


@router.get("/admin/products/{product_uuid}", response_class=HTMLResponse)
def admin_product_detail(
    product_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        # Include inactive rows so orphaned soft-deleted products can be Removed.
        product = ctx.products.load_product_for_delete(db, product_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/products", status_code=303)
    payload = product_to_response(product)
    return templates.TemplateResponse(
        request,
        "admin_product_form.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "error": None,
            "mode": "edit",
            "form": _product_form(
                name=payload.name,
                number=payload.number or "",
                description=payload.description or "",
                vault_folder=payload.vault_folder,
                state=payload.state,
                read_only=payload.read_only,
                uuid=payload.uuid,
            ),
            "delete_error": None,
            "product_states": list(ProductState),
            "product_state_labels": PRODUCT_STATE_LABELS,
        },
    )


@router.post("/admin/products/{product_uuid}", response_class=HTMLResponse)
def admin_product_update(
    product_uuid: str,
    request: Request,
    name: str = Form(...),
    number: str = Form(""),
    description: str = Form(""),
    vault_folder: str = Form(""),
    state: str = Form("IN_WORK"),
    read_only: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    try:
        product = ctx.products.get_product(db, product_uuid)
    except CreoPDMError:
        return RedirectResponse("/admin/products", status_code=303)
    is_read_only = str(read_only or "").strip().lower() in {"1", "true", "on", "yes"}
    form = _product_form(
        name=name,
        number=number,
        description=description,
        vault_folder=product.vault_folder or product.uuid,
        state=state,
        read_only=is_read_only,
        uuid=product.uuid,
    )
    try:
        from creopdm.utils.vault_folder import reject_vault_folder_change

        # Disabled inputs are omitted from POST; if vault_folder is forced in, reject renames.
        reject_vault_folder_change(product, vault_folder)
        ctx.products.update_product(
            db,
            product_uuid,
            name=name,
            number=number or None,
            description=description or None,
            state=state,
            read_only=is_read_only,
        )
        db.commit()
        return RedirectResponse("/admin/products", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_product_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": exc.message,
                "mode": "edit",
                "form": form,
                "delete_error": None,
                "product_states": list(ProductState),
                "product_state_labels": PRODUCT_STATE_LABELS,
            },
            status_code=400,
        )


@router.post("/admin/products/{product_uuid}/delete", response_class=HTMLResponse)
def admin_product_delete_moved(
    product_uuid: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    """Legacy edit-product delete URL → Utilities → Delete products."""
    manager = _require_products_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return RedirectResponse("/admin/utilities/delete-products", status_code=303)


def _require_email_manager(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_manage_email(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Email configuration access required (email.manage).</p>",
            status_code=403,
        )
    return user


def _require_utilities_access(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not ctx.user_accounts.can_access_utilities(user):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Utilities access required (utilities.access).</p>",
            status_code=403,
        )
    return user


def _require_utilities_or_settings(
    request: Request, ctx: AppContext, db: Session
) -> User | HTMLResponse | RedirectResponse:
    """Availability lives under Utilities; settings managers can still open the pill link."""
    user_uuid = request.session.get(SESSION_USER_KEY)
    user = ctx.user_accounts.get_by_uuid(db, str(user_uuid)) if user_uuid else None
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if ctx.user_accounts.can_access_utilities(user) or ctx.user_accounts.can_manage_settings(
        user
    ):
        return user
    return HTMLResponse(
        "<h1>403 Forbidden</h1><p>Utilities or Settings access required.</p>",
        status_code=403,
    )


_DEFAULT_TEST_SUBJECT = "CreoPDM test email"
_DEFAULT_TEST_MESSAGE = (
    "This is a test message from CreoPDM Administration → Email.\n"
)


def _email_form_from_settings(
    ctx: AppContext,
    *,
    test_to: str = "",
    test_subject: str | None = None,
    test_message: str | None = None,
) -> dict:
    email = ctx.settings.email
    transport = email.transport if email.transport in {"local", "smtp"} else "local"
    return {
        "enabled": bool(email.enabled),
        "transport": transport,
        "smtp_host": email.smtp_host or "127.0.0.1",
        "smtp_port": int(email.smtp_port or 25),
        "from_address": email.from_address or "",
        "from_name": email.from_name or "",
        "administrator_email": email.administrator_email or "",
        "smtp_username": email.smtp_username or "",
        "has_password": bool(email.smtp_password),
        "smtp_use_tls": bool(email.smtp_use_tls),
        "smtp_use_auth": bool(email.smtp_use_auth),
        "test_to": test_to,
        "test_subject": (
            _DEFAULT_TEST_SUBJECT if test_subject is None else test_subject
        ),
        "test_message": (
            _DEFAULT_TEST_MESSAGE if test_message is None else test_message
        ),
    }


def _email_form_from_post(
    *,
    enabled: str,
    transport: str,
    smtp_host: str,
    smtp_port: str,
    from_address: str,
    from_name: str,
    administrator_email: str,
    smtp_username: str,
    smtp_password: str,
    smtp_use_tls: str,
    smtp_use_auth: str,
    test_to: str,
    test_subject: str,
    test_message: str,
    has_password: bool,
) -> dict:
    mode = (transport or "local").strip().lower()
    if mode not in {"local", "smtp"}:
        mode = "local"
    try:
        port = int((smtp_port or "25").strip() or "25")
    except ValueError:
        port = 25
    subject = (test_subject or "").strip() or _DEFAULT_TEST_SUBJECT
    # Preserve user-edited body (including empty); fall back only when field omitted.
    message = _DEFAULT_TEST_MESSAGE if test_message is None else test_message
    return {
        "enabled": enabled == "1",
        "transport": mode,
        "smtp_host": (smtp_host or "").strip() or "127.0.0.1",
        "smtp_port": port,
        "from_address": (from_address or "").strip(),
        "from_name": (from_name or "").strip(),
        "administrator_email": (administrator_email or "").strip(),
        "smtp_username": (smtp_username or "").strip(),
        "has_password": has_password or bool((smtp_password or "").strip()),
        "smtp_use_tls": smtp_use_tls == "1",
        "smtp_use_auth": smtp_use_auth == "1",
        "test_to": (test_to or "").strip(),
        "test_subject": subject,
        "test_message": message,
    }


def _email_form_is_dirty(
    form: dict,
    current,
    *,
    smtp_password_posted: str,
) -> bool:
    """True when posted settings differ from last saved EmailConfig (test_to ignored)."""
    if bool(form["enabled"]) != bool(current.enabled):
        return True
    if form["transport"] != (current.transport or "local"):
        return True
    if form["from_address"] != (current.from_address or ""):
        return True
    if form["from_name"] != (current.from_name or ""):
        return True
    if form["administrator_email"] != (current.administrator_email or ""):
        return True
    if (smtp_password_posted or "").strip():
        return True
    if form["transport"] != "smtp":
        return False
    if form["smtp_host"] != (current.smtp_host or "127.0.0.1"):
        return True
    if int(form["smtp_port"]) != int(current.smtp_port or 25):
        return True
    if form["smtp_username"] != (current.smtp_username or ""):
        return True
    if bool(form["smtp_use_tls"]) != bool(current.smtp_use_tls):
        return True
    if bool(form["smtp_use_auth"]) != bool(current.smtp_use_auth):
        return True
    return False


@router.get("/admin/email", response_class=HTMLResponse)
def admin_email_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_email_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return templates.TemplateResponse(
        request,
        "admin_email.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "form": _email_form_from_settings(ctx),
            "error": None,
            "success": None,
        },
    )


@router.post("/admin/email", response_class=HTMLResponse)
def admin_email_submit(
    request: Request,
    action: str = Form("save"),
    enabled: str = Form(""),
    transport: str = Form("local"),
    smtp_host: str = Form("127.0.0.1"),
    smtp_port: str = Form("25"),
    from_address: str = Form(""),
    from_name: str = Form(""),
    administrator_email: str = Form(""),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str = Form(""),
    smtp_use_auth: str = Form(""),
    test_to: str = Form(""),
    test_subject: str = Form(_DEFAULT_TEST_SUBJECT),
    test_message: str = Form(_DEFAULT_TEST_MESSAGE),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_email_manager(request, ctx, db)
    if _is_blocked(manager):
        return manager

    current = ctx.settings.email
    current_password = current.smtp_password or ""
    form = _email_form_from_post(
        enabled=enabled,
        transport=transport,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        from_address=from_address,
        from_name=from_name,
        administrator_email=administrator_email,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_use_tls=smtp_use_tls,
        smtp_use_auth=smtp_use_auth,
        test_to=test_to,
        test_subject=test_subject,
        test_message=test_message,
        has_password=bool(current_password),
    )
    # Keep SMTP panel values from saved settings when local (hidden fields may be empty).
    if form["transport"] == "local":
        form["smtp_host"] = current.smtp_host or "127.0.0.1"
        form["smtp_port"] = int(current.smtp_port or 25)
        form["smtp_username"] = current.smtp_username or ""
        form["smtp_use_tls"] = bool(current.smtp_use_tls)
        form["smtp_use_auth"] = bool(current.smtp_use_auth)
        form["has_password"] = bool(current_password)

    def _render(*, error: str | None = None, success: str | None = None, status_code: int = 200):
        return templates.TemplateResponse(
            request,
            "admin_email.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "form": form,
                "error": error,
                "success": success,
            },
            status_code=status_code,
        )

    if action == "test":
        if _email_form_is_dirty(form, current, smtp_password_posted=smtp_password):
            return _render(
                error="Save your changes before sending a test email.",
                status_code=400,
            )
        recipient = form["test_to"] or (current.administrator_email or "")
        form = _email_form_from_settings(
            ctx,
            test_to=form["test_to"],
            test_subject=form["test_subject"],
            test_message=form["test_message"],
        )
        if not recipient:
            return _render(
                error="Set an administrator email or a test recipient before sending.",
                status_code=400,
            )
        try:
            ctx.email.send(
                recipient,
                form["test_subject"],
                form["test_message"],
            )
        except CreoPDMError as exc:
            return _render(error=exc.message, status_code=400)
        return _render(success=f"Test email sent to {recipient}.")

    new_settings = ctx.settings.model_copy(deep=True)
    email = new_settings.email
    email.enabled = form["enabled"]
    email.transport = form["transport"]
    email.from_address = form["from_address"]
    email.from_name = form["from_name"]
    email.administrator_email = form["administrator_email"]
    if form["transport"] == "smtp":
        email.smtp_host = form["smtp_host"]
        email.smtp_port = form["smtp_port"]
        email.smtp_username = form["smtp_username"]
        email.smtp_use_tls = form["smtp_use_tls"]
        email.smtp_use_auth = form["smtp_use_auth"]
        new_password = (smtp_password or "").strip()
        if new_password:
            email.smtp_password = new_password
        else:
            email.smtp_password = current_password
    # Local: keep previously saved SMTP credentials for when the admin switches back.
    form["has_password"] = bool(email.smtp_password)
    form["smtp_host"] = email.smtp_host or "127.0.0.1"
    form["smtp_port"] = int(email.smtp_port or 25)
    form["smtp_username"] = email.smtp_username or ""
    form["smtp_use_tls"] = bool(email.smtp_use_tls)
    form["smtp_use_auth"] = bool(email.smtp_use_auth)

    try:
        from creopdm.config import EmailConfig
        from pydantic import ValidationError

        EmailConfig.model_validate(email.model_dump())
    except ValidationError as exc:
        msg = "; ".join(err.get("msg", str(err)) for err in exc.errors())
        return _render(error=msg or str(exc), status_code=400)

    ctx.config.save(new_settings)
    ctx.settings = new_settings
    password_changed = bool((smtp_password or "").strip())
    ctx.activities.record(
        db,
        ActivityAction.SYSTEM_SETTING_CHANGED,
        _audit_actor(ctx),
        details={
            "setting": "email",
            "enabled": bool(email.enabled),
            "transport": email.transport,
            "from_address": email.from_address or "",
            "administrator_email": email.administrator_email or "",
            "smtp_host": email.smtp_host or "",
            "smtp_port": int(email.smtp_port or 25),
            "smtp_username": email.smtp_username or "",
            "smtp_use_tls": bool(email.smtp_use_tls),
            "smtp_use_auth": bool(email.smtp_use_auth),
            "smtp_password_changed": password_changed,
            # Never store the password — redact_audit_details also masks *password* keys.
            "smtp_password": "[REDACTED]" if password_changed else None,
        },
    )
    db.commit()
    form = _email_form_from_settings(
        ctx,
        test_to=form["test_to"],
        test_subject=form["test_subject"],
        test_message=form["test_message"],
    )
    return _render(success="Email settings saved.")


_DEFAULT_BROADCAST_SUBJECT = "Message from CreoPDM"


def _utilities_hub_response(
    request: Request,
    ctx: AppContext,
    manager: User,
):
    return templates.TemplateResponse(
        request,
        "admin_utilities.html",
        {**_base_ctx(request, ctx, current_user=manager)},
    )


def _utilities_availability_response(
    request: Request,
    ctx: AppContext,
    manager: User,
):
    from creopdm.api.settings import settings_to_response

    return templates.TemplateResponse(
        request,
        "admin_utilities_availability.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "settings": settings_to_response(ctx),
        },
    )


def _utilities_email_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
    *,
    broadcast_subject: str = _DEFAULT_BROADCAST_SUBJECT,
    broadcast_message: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    from creopdm.services.utilities_service import active_user_emails

    return templates.TemplateResponse(
        request,
        "admin_utilities_email.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "broadcast_recipient_count": len(active_user_emails(db)),
            "broadcast_subject": broadcast_subject,
            "broadcast_message": broadcast_message,
            "error": error,
            "success": success,
        },
        status_code=status_code,
    )


def _utilities_compact_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
    *,
    compact_product_id: str = "",
    compact_confirm_name: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    from creopdm.services.utilities_service import list_products_for_compact

    return templates.TemplateResponse(
        request,
        "admin_utilities_compact.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "compact_products": list_products_for_compact(db),
            "compact_product_id": compact_product_id,
            "compact_confirm_name": compact_confirm_name,
            "error": error,
            "success": success,
        },
        status_code=status_code,
    )


def _utilities_rebuild_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
    *,
    rebuild_product_id: str = "",
    rebuild_confirm_name: str = "",
    rebuild_action: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    from creopdm.services.utilities_service import list_products_for_compact

    return templates.TemplateResponse(
        request,
        "admin_utilities_rebuild.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "rebuild_products": list_products_for_compact(db),
            "rebuild_product_id": rebuild_product_id,
            "rebuild_confirm_name": rebuild_confirm_name,
            "rebuild_action": rebuild_action,
            "error": error,
            "success": success,
        },
        status_code=status_code,
    )


def _utilities_repair_success_message(result) -> str:
    """Plain-language success line for Rebuild / clear metadata / rebuild Where Used."""
    parts: list[str] = []
    if result.rebuilt:
        tip = (result.head or "")[:12]
        tip_bit = f" from vault tip {tip}" if tip else ""
        parts.append(
            f"rebuilt file list{tip_bit} "
            f"(removed {result.objects_removed} old file row(s), "
            f"registered {result.files_registered} tip file(s))"
        )
    elif result.metadata_cleared:
        parts.append(
            f"deleted Creo metadata from {result.metadata_versions} version row(s)"
        )
    if result.where_used_rebuilt:
        parts.append("started Where Used indexing")
    body = "; ".join(parts) if parts else "updated the product database"
    hints: list[str] = []
    if result.rebuilt and not result.where_used_rebuilt:
        hints.append(
            "Run Rebuild Where Used if you need Top Level / dependencies again"
        )
    if result.metadata_cleared:
        hints.append("collect metadata again if needed")
    if hints:
        body += ". " + "; ".join(hints)
    return f"Updated {result.product_name}: {body}."


def _utilities_health_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
):
    from creopdm.services.utilities_service import collect_utilities_status

    return templates.TemplateResponse(
        request,
        "admin_utilities_health.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "status": collect_utilities_status(ctx, db),
        },
    )


def _utilities_delete_products_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
    *,
    delete_product_id: str = "",
    delete_confirm_name: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    from creopdm.services.utilities_service import list_products_for_compact

    return templates.TemplateResponse(
        request,
        "admin_utilities_delete_products.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "delete_products": list_products_for_compact(db),
            "delete_product_id": delete_product_id,
            "delete_confirm_name": delete_confirm_name,
            "error": error,
            "success": success,
        },
        status_code=status_code,
    )


def _audit_action_choices() -> list[tuple[str, str]]:
    """Stable filter labels for Utilities → Audit log."""
    labels = {
        ActivityAction.PRODUCT_CREATED: "Product created",
        ActivityAction.PRODUCT_UPDATED: "Product updated",
        ActivityAction.OBJECT_ADDED: "Object added",
        ActivityAction.OBJECT_REMOVED: "Object removed",
        ActivityAction.WORKSPACE_CLEARED: "Workspace cleared",
        ActivityAction.CHECKED_OUT: "Checked out",
        ActivityAction.CHECKOUT_CANCELLED: "Checkout cancelled",
        ActivityAction.CHECKOUT_OVERRIDE: "Checkout override",
        ActivityAction.CHECKED_IN: "Checked in",
        ActivityAction.VERSION_RESTORED: "Version restored",
        ActivityAction.VAULT_HISTORY_COMPACTED: "Vault history compacted",
        ActivityAction.PRODUCT_DB_REBUILT: "Product DB rebuilt",
        ActivityAction.USER_CREATED: "User created",
        ActivityAction.USER_DISABLED: "User disabled",
        ActivityAction.USER_ENABLED: "User enabled",
        ActivityAction.ROLE_CHANGED: "Role changed",
        ActivityAction.MEMBERSHIP_CHANGED: "Membership changed",
        ActivityAction.SYSTEM_SETTING_CHANGED: "System setting changed",
    }
    return [(action.value, labels.get(action, action.value)) for action in labels]


def _parse_audit_day(raw: str | None, *, end_of_day: bool = False):
    """Parse YYYY-MM-DD filter into timezone-aware UTC bounds (or None)."""
    from datetime import datetime, timezone

    text = (raw or "").strip()
    if not text:
        return None
    try:
        day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if end_of_day:
        return day.replace(hour=23, minute=59, second=59, microsecond=999999)
    return day


def _utilities_audit_response(
    request: Request,
    ctx: AppContext,
    db: Session,
    manager: User,
    *,
    since: str = "",
    until: str = "",
    action: str = "",
    username: str = "",
    product_uuid: str = "",
    object_query: str = "",
):
    from creopdm.services.activity_service import AUDIT_PAGE_SIZE

    events = ctx.activities.list_events(
        db,
        action=action or None,
        username=username or None,
        product_uuid=product_uuid or None,
        object_query=object_query or None,
        since=_parse_audit_day(since),
        until=_parse_audit_day(until, end_of_day=True),
    )
    return templates.TemplateResponse(
        request,
        "admin_utilities_audit.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "events": events,
            "page_size": AUDIT_PAGE_SIZE,
            "action_choices": _audit_action_choices(),
            "filters": {
                "since": since or "",
                "until": until or "",
                "action": action or "",
                "username": username or "",
                "product_uuid": product_uuid or "",
                "object": object_query or "",
            },
        },
    )


def _utilities_logs_response(
    request: Request,
    ctx: AppContext,
    manager: User,
    *,
    name: str | None = None,
):
    from creopdm.services.utilities_service import load_server_log_view

    view = load_server_log_view(ctx, name=name)
    return templates.TemplateResponse(
        request,
        "admin_utilities_logs.html",
        {
            **_base_ctx(request, ctx, current_user=manager),
            "logs_dir_display": view.logs_dir_display,
            "files": view.files,
            "selected_name": view.selected_name,
            "content": view.content,
            "truncated": view.truncated,
            "error": view.error,
        },
    )


@router.get("/admin/utilities", response_class=HTMLResponse)
def admin_utilities_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_hub_response(request, ctx, manager)


@router.get("/admin/utilities/availability", response_class=HTMLResponse)
def admin_utilities_availability_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_or_settings(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_availability_response(request, ctx, manager)


@router.get("/admin/utilities/email-all", response_class=HTMLResponse)
def admin_utilities_email_all_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_email_response(request, ctx, db, manager)


@router.get("/admin/utilities/compact", response_class=HTMLResponse)
def admin_utilities_compact_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_compact_response(request, ctx, db, manager)


@router.get("/admin/utilities/rebuild-product", response_class=HTMLResponse)
def admin_utilities_rebuild_product_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_rebuild_response(request, ctx, db, manager)


@router.get("/admin/utilities/health", response_class=HTMLResponse)
def admin_utilities_health_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_health_response(request, ctx, db, manager)


@router.get("/admin/utilities/delete-products", response_class=HTMLResponse)
def admin_utilities_delete_products_page(
    request: Request, ctx: AppContext = Depends(get_context), db: Session = Depends(get_db)
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_delete_products_response(request, ctx, db, manager)


@router.get("/admin/utilities/audit", response_class=HTMLResponse)
def admin_utilities_audit_page(
    request: Request,
    since: str = Query(""),
    until: str = Query(""),
    action: str = Query(""),
    username: str = Query(""),
    product_uuid: str = Query(""),
    object_query: str = Query("", alias="object"),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_audit_response(
        request,
        ctx,
        db,
        manager,
        since=since,
        until=until,
        action=action,
        username=username,
        product_uuid=product_uuid,
        object_query=object_query,
    )


@router.post("/admin/utilities/delete-products", response_class=HTMLResponse)
def admin_utilities_delete_products(
    request: Request,
    product_id: str = Form(""),
    confirm_name: str = Form(""),
    confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    pid = (product_id or "").strip()
    typed = confirm_name or ""
    if confirm != "1":
        return _utilities_delete_products_response(
            request,
            ctx,
            db,
            manager,
            delete_product_id=pid,
            delete_confirm_name=typed,
            error="Confirm that you want to permanently delete this product’s vault.",
            status_code=400,
        )
    try:
        product = ctx.products.load_product_for_delete(db, pid)
    except CreoPDMError as exc:
        return _utilities_delete_products_response(
            request,
            ctx,
            db,
            manager,
            delete_product_id=pid,
            delete_confirm_name=typed,
            error=exc.message,
            status_code=400,
        )
    if (typed or "").strip() != product.name:
        return _utilities_delete_products_response(
            request,
            ctx,
            db,
            manager,
            delete_product_id=pid,
            delete_confirm_name=typed,
            error="Type the exact product name to confirm removal.",
            status_code=400,
        )
    try:
        workspace = ctx.workspaces.vault_for(product)
        result = ctx.products.forget_product(
            db,
            pid,
            confirm_name=typed,
            workspace_path=workspace,
        )
    except CreoPDMError as exc:
        db.rollback()
        return _utilities_delete_products_response(
            request,
            ctx,
            db,
            manager,
            delete_product_id=pid,
            delete_confirm_name=typed,
            error=exc.message,
            status_code=400,
        )
    note = f"Deleted product {result['name']} and its CreoPDM vault."
    if result.get("warning"):
        note = f"{note} {result['warning']}"
    return _utilities_delete_products_response(
        request,
        ctx,
        db,
        manager,
        success=note,
    )


@router.get("/admin/utilities/logs", response_class=HTMLResponse)
def admin_utilities_logs_page(
    request: Request,
    name: str | None = None,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    return _utilities_logs_response(request, ctx, manager, name=name)


@router.post("/admin/utilities/email-all", response_class=HTMLResponse)
def admin_utilities_email_all(
    request: Request,
    subject: str = Form(""),
    message: str = Form(""),
    confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    from creopdm.services.utilities_service import send_email_to_all_users

    subj = (subject or "").strip()
    body = message or ""
    if confirm != "1":
        return _utilities_email_response(
            request,
            ctx,
            db,
            manager,
            broadcast_subject=subj or _DEFAULT_BROADCAST_SUBJECT,
            broadcast_message=body,
            error="Confirm that you want to email all active users.",
            status_code=400,
        )
    try:
        result = send_email_to_all_users(ctx, db, subject=subj, message=body)
    except CreoPDMError as exc:
        return _utilities_email_response(
            request,
            ctx,
            db,
            manager,
            broadcast_subject=subj or _DEFAULT_BROADCAST_SUBJECT,
            broadcast_message=body,
            error=exc.message,
            status_code=400,
        )
    if result.failed:
        detail = f" Sent {result.sent} of {result.recipient_count}; {result.failed} failed."
        if result.errors:
            detail += " " + "; ".join(result.errors)
        return _utilities_email_response(
            request,
            ctx,
            db,
            manager,
            broadcast_subject=_DEFAULT_BROADCAST_SUBJECT,
            broadcast_message="",
            success=detail.strip(),
        )
    return _utilities_email_response(
        request,
        ctx,
        db,
        manager,
        broadcast_subject=_DEFAULT_BROADCAST_SUBJECT,
        broadcast_message="",
        success=f"Email sent to {result.sent} active user{'s' if result.sent != 1 else ''}.",
    )


@router.post("/admin/utilities/compact-vault", response_class=HTMLResponse)
def admin_utilities_compact_vault(
    request: Request,
    product_id: str = Form(""),
    confirm_name: str = Form(""),
    confirm: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    from creopdm.services.utilities_service import compact_product_vault_history

    pid = (product_id or "").strip()
    typed = confirm_name or ""
    if confirm != "1":
        return _utilities_compact_response(
            request,
            ctx,
            db,
            manager,
            compact_product_id=pid,
            compact_confirm_name=typed,
            error="Confirm that you want to permanently destroy older History for this product.",
            status_code=400,
        )
    try:
        result = compact_product_vault_history(
            ctx,
            db,
            product_uuid=pid,
            confirm_name=typed,
        )
        db.commit()
    except CreoPDMError as exc:
        db.rollback()
        return _utilities_compact_response(
            request,
            ctx,
            db,
            manager,
            compact_product_id=pid,
            compact_confirm_name=typed,
            error=exc.message,
            status_code=400,
        )
    versions = result.versions_removed
    version_note = (
        f" Removed {versions} older History version{'s' if versions != 1 else ''}."
        if versions
        else ""
    )
    return _utilities_compact_response(
        request,
        ctx,
        db,
        manager,
        success=(
            f"Compacted vault history for {result.product_name}. "
            f"{result.size_summary}.{version_note}"
        ).strip(),
    )


@router.post("/admin/utilities/rebuild-product-db", response_class=HTMLResponse)
def admin_utilities_rebuild_product_db(
    request: Request,
    background_tasks: BackgroundTasks,
    product_id: str = Form(""),
    confirm_name: str = Form(""),
    confirm: str = Form(""),
    repair_action: str = Form(""),
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
):
    manager = _require_utilities_access(request, ctx, db)
    if _is_blocked(manager):
        return manager
    from creopdm.services.utilities_service import repair_product_database

    pid = (product_id or "").strip()
    typed = confirm_name or ""
    action = (repair_action or "").strip()
    want_rebuild = action == "rebuild"
    want_metadata = action == "clear_metadata"
    want_where_used = action == "rebuild_where_used"
    form_state = dict(
        rebuild_product_id=pid,
        rebuild_confirm_name=typed,
        rebuild_action=action if action in {"rebuild", "clear_metadata", "rebuild_where_used"} else "",
    )
    if confirm != "1":
        return _utilities_rebuild_response(
            request,
            ctx,
            db,
            manager,
            error="Confirm that you want to change this product’s database as selected.",
            status_code=400,
            **form_state,
        )
    if not (want_rebuild or want_metadata or want_where_used):
        return _utilities_rebuild_response(
            request,
            ctx,
            db,
            manager,
            error=(
                "Choose one action: rebuild from vault, delete Creo metadata, "
                "or delete and rebuild Where Used."
            ),
            status_code=400,
            **form_state,
        )
    try:
        result = repair_product_database(
            ctx,
            db,
            product_uuid=pid,
            confirm_name=typed,
            rebuild=want_rebuild,
            clear_metadata=want_metadata,
            rebuild_where_used=want_where_used,
        )
        db.commit()
    except CreoPDMError as exc:
        db.rollback()
        return _utilities_rebuild_response(
            request,
            ctx,
            db,
            manager,
            error=exc.message,
            status_code=400,
            **form_state,
        )
    if want_where_used:
        # Defer until after the HTML response and request DB session close.
        # Do not sync-start under the open request session (indexer write lock
        # blocked the form fetch). Page JS POSTs Start for instant N of M;
        # this BackgroundTask covers plain form POST when JS is unavailable.
        background_tasks.add_task(ctx.where_used_index.start, pid)
    return _utilities_rebuild_response(
        request,
        ctx,
        db,
        manager,
        success=_utilities_repair_success_message(result),
    )
