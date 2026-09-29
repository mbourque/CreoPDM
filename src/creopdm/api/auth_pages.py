"""HTML + form endpoints for setup, login, logout, password, and user admin."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
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
from creopdm.constants import APP_NAME, APP_VERSION, PRODUCT_STATE_LABELS, ProductState
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
        for p in ctx.products.list_products(db)
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
            ctx.user_accounts.create_user(
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
    all_products_count = sum(1 for u in users if getattr(u, "access_all_products", True))
    restricted = [u for u in users if not getattr(u, "access_all_products", True)]
    product_rows = []
    for p in ctx.products.list_products(db):
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
    for p in ctx.products.list_products(db):
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
        ctx.user_accounts.set_product_access(
            db,
            user,
            access_all=access_all,
            product_uuids=product_uuids if not access_all else None,
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
        ctx.user_accounts.set_restricted_product_members(
            db, product, member_user_uuids=members, actor=manager
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
    products = [product_to_response(p) for p in ctx.products.list_products(db)]
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
        product = ctx.products.get_product(db, product_uuid)
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
def admin_product_delete(
    product_uuid: str,
    request: Request,
    confirm_name: str = Form(...),
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
    payload = product_to_response(product)
    form = _product_form(
        name=payload.name,
        number=payload.number or "",
        description=payload.description or "",
        vault_folder=payload.vault_folder,
        state=payload.state,
        read_only=payload.read_only,
        uuid=payload.uuid,
    )
    form_extras = {
        "product_states": list(ProductState),
        "product_state_labels": PRODUCT_STATE_LABELS,
    }
    if (confirm_name or "").strip() != product.name:
        return templates.TemplateResponse(
            request,
            "admin_product_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": None,
                "mode": "edit",
                "form": form,
                "delete_error": "Type the exact product name to confirm removal.",
                **form_extras,
            },
            status_code=400,
        )
    try:
        ctx.products.delete_product(db, product_uuid)
        db.commit()
        return RedirectResponse("/admin/products", status_code=303)
    except CreoPDMError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "admin_product_form.html",
            {
                **_base_ctx(request, ctx, current_user=manager),
                "error": None,
                "mode": "edit",
                "form": form,
                "delete_error": exc.message,
                **form_extras,
            },
            status_code=400,
        )


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
    form = _email_form_from_settings(
        ctx,
        test_to=form["test_to"],
        test_subject=form["test_subject"],
        test_message=form["test_message"],
    )
    return _render(success="Email settings saved.")
