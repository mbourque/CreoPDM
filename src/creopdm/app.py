"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from creopdm.api import auth_pages, checkout, creo, health, objects, pages, products, settings, utilities
from creopdm.api.errors import register_error_handlers
from creopdm.auth_constants import UserStatus
from creopdm.auth_session import (
    SESSION_USER_KEY,
    bearer_token_from_header,
    ensure_session_secret,
    mint_agent_token,
    verify_agent_token,
)
from creopdm.config import ConfigManager
from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.context import AppContext
from creopdm.creo.connector_factory import create_creo_connector
from creopdm.database.migrate import run_migrations
from creopdm.database.session import create_db_engine, create_session_factory
from creopdm.logging_setup import get_logger, setup_logging
from creopdm.permissions import apply_caps, empty_caps, caps_for_user, test_auth_caps
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkin_service import CheckinService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.creo_service import CreoService
from creopdm.services.email_service import EmailService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.metadata_service import MetadataService
from creopdm.services.notification_service import NotificationService
from creopdm.services.object_service import ObjectService
from creopdm.services.password_reset_service import PasswordResetService
from creopdm.services.product_service import ProductService
from creopdm.services.product_watch_service import ProductWatchService
from creopdm.services.user_service import UserService
from creopdm.services.where_used_index_jobs import WhereUsedIndexJobs
from creopdm.services.zip_import_jobs import ZipImportJobs
from creopdm.services.workspace_service import WorkspaceService
from creopdm.storage.git_store import GitVersionStore
from creopdm.utils.identity import (
    CurrentUserProvider,
    SessionAwareUserProvider,
    StaticUserProvider,
    UserIdentity,
    set_request_identity,
)

PACKAGE_DIR = Path(__file__).resolve().parent
logger = get_logger("app")


def build_context(config: ConfigManager | None = None, users: CurrentUserProvider | None = None) -> AppContext:
    manager = config or ConfigManager()
    app_settings = manager.load()
    setup_logging(manager.log_path)
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)
    run_migrations(manager.database_url())
    engine = create_db_engine(manager.database_url())
    session_factory = create_session_factory(engine)
    git = GitService(app_settings.git.executable)
    version_store = GitVersionStore(git)
    auth_enabled = users is None
    identity: CurrentUserProvider = users if users is not None else SessionAwareUserProvider()
    locks = ProductLockManager()
    activities = ActivityService()
    workspaces = WorkspaceService(manager, git)
    objects = ObjectService(version_store, locks, activities, identity, manager)
    checkouts = CheckoutService(objects, workspaces, locks, activities, identity)
    creo_connector = create_creo_connector(
        app_settings.creo.connector,
        app_settings.creo.executable,
        app_settings.creo.open_mode,
        app_settings.creo.view_executable,
        app_settings.creo.view_open_mode,
        app_settings.creo.js_library,
    )
    checkins = CheckinService(
        objects,
        checkouts,
        workspaces,
        version_store,
        locks,
        activities,
        identity,
        creo_connector,
    )
    metadata = MetadataService(objects, workspaces)
    user_accounts = UserService()
    email = EmailService()
    notifications = NotificationService(get_config=lambda: manager.settings.email, email=email)
    product_watches = ProductWatchService(notifications)
    password_resets = PasswordResetService(user_accounts, email, notifications)
    with session_factory() as db:
        user_accounts.ensure_builtin_roles(db)
        db.commit()
    ctx = AppContext(
        config=manager,
        settings=app_settings,
        engine=engine,
        session_factory=session_factory,
        git=git,
        version_store=version_store,
        users=identity,
        locks=locks,
        creo=creo_connector,
        activities=activities,
        products=ProductService(git, locks, activities, identity, workspaces),
        objects=objects,
        workspaces=workspaces,
        checkouts=checkouts,
        checkins=checkins,
        creo_service=CreoService(
            creo_connector, objects, checkouts, workspaces, metadata=metadata
        ),
        metadata=metadata,
        where_used_index=WhereUsedIndexJobs(session_factory, metadata),
        zip_imports=ZipImportJobs(),
        email=email,
        notifications=notifications,
        product_watches=product_watches,
        password_resets=password_resets,
        user_accounts=user_accounts,
        auth_enabled=auth_enabled,
    )
    # Prefer live ctx.settings after apply_settings / email form saves.
    email.configure(lambda: ctx.settings.email)
    notifications.configure(lambda: ctx.settings.email)
    return ctx



def create_app(context: AppContext | None = None) -> FastAPI:
    ctx = context or build_context()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("%s is running", APP_NAME)
        ctx.workspaces.sync_gitignore()
        try:
            yield
        finally:
            logger.info("%s shutdown", APP_NAME)
            ctx.engine.dispose()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", lifespan=lifespan)
    app.state.ctx = ctx
    register_error_handlers(app)
    app.include_router(auth_pages.router)
    app.include_router(health.router)
    app.include_router(utilities.router)
    app.include_router(settings.router)
    app.include_router(products.router)
    app.include_router(objects.router)
    app.include_router(checkout.router)
    app.include_router(creo.router)
    app.include_router(pages.router)
    static_dir = PACKAGE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app_js = static_dir / "js" / "app.js"

    @app.get("/client/app.js")
    def client_app_js() -> FileResponse:
        return FileResponse(
            app_js,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.middleware("http")
    async def no_store_app_js(request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path.endswith("/app.js"):
            response.headers["Cache-Control"] = "no-store"
        # Authenticated HTML must not be reused across logins (stale watch bell / user pill).
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            response.headers["Cache-Control"] = "no-store"
        return response

    # Outermost so request.session is available in auth_guard.
    secret = ensure_session_secret(ctx.config.config_dir)
    app.state.session_secret = secret

    @app.middleware("http")
    async def auth_guard(request, call_next):
        set_request_identity(None)
        request.state.auth_user = None
        request.state.agent_token = ""
        apply_caps(request, empty_caps())
        path = request.url.path or "/"

        public = path in {
            "/login",
            "/setup",
            "/logout",
            "/forgot-password",
            "/reset-password",
            "/api/health",
            "/api/docs",
            "/openapi.json",
            "/favicon.ico",
        } or path.startswith("/static") or path.startswith("/client/")

        if not ctx.auth_enabled:
            # Tests / StaticUserProvider: no login gate; full caps for existing suite.
            apply_caps(request, test_auth_caps())
            if isinstance(ctx.users, StaticUserProvider):
                set_request_identity(ctx.users.get_current_user())
            try:
                return await call_next(request)
            finally:
                set_request_identity(None)

        db = ctx.session_factory()
        try:
            needs_setup = ctx.user_accounts.needs_setup(db)
            user = None
            user_uuid = request.session.get(SESSION_USER_KEY)
            if user_uuid:
                user = ctx.user_accounts.get_by_uuid(db, str(user_uuid))
                if user is not None and user.status != UserStatus.ACTIVE.value:
                    request.session.clear()
                    user = None

            if user is None:
                bearer = bearer_token_from_header(request.headers.get("authorization"))
                if bearer:
                    token_uid = verify_agent_token(bearer, secret)
                    if token_uid:
                        user = ctx.user_accounts.get_by_uuid(db, token_uid)
                        if user is not None and user.status != UserStatus.ACTIVE.value:
                            user = None

            if user is not None:
                identity = UserIdentity(
                    user_name=user.username,
                    machine_name="web",
                    user_uuid=user.uuid,
                    display_name=user.display_name,
                )
                set_request_identity(identity)
                request.state.auth_user = user
                request.state.agent_token = mint_agent_token(user.uuid, secret)
                apply_caps(request, caps_for_user(ctx.user_accounts, user))

            if needs_setup and not public and not path.startswith("/setup"):
                return RedirectResponse("/setup", status_code=303)
            if not needs_setup and path.startswith("/setup"):
                return RedirectResponse("/login", status_code=303)

            if not public and user is None:
                if path.startswith("/api/"):
                    return JSONResponse(
                        {
                            "error": {
                                "code": "UNAUTHORIZED",
                                "message": "Sign in required.",
                                "details": {},
                            }
                        },
                        status_code=401,
                    )
                next_url = quote(path + (("?" + request.url.query) if request.url.query else ""))
                return RedirectResponse(f"/login?next={next_url}", status_code=303)

            if (
                user is not None
                and user.must_change_password
                and not path.startswith("/account/password")
                and not path.startswith("/logout")
                and not path.startswith("/static")
                and not path.startswith("/api/")
            ):
                return RedirectResponse("/account/password", status_code=303)

            # Display-only maintenance: swap HTML for non-admins. Never touch /api/
            # (in-flight check-in, upload, Git must keep running).
            if (
                user is not None
                and request.method in {"GET", "HEAD"}
                and not path.startswith("/api/")
                and not path.startswith("/static")
                and not path.startswith("/client/")
                and path
                not in {
                    "/login",
                    "/logout",
                    "/setup",
                    "/forgot-password",
                    "/reset-password",
                    "/favicon.ico",
                }
                and not path.startswith("/account/password")
                and not path.startswith("/creojs")
            ):
                from creopdm.site_availability import (
                    site_is_unavailable,
                    user_bypasses_site_unavailable,
                )

                if site_is_unavailable(ctx.settings) and not user_bypasses_site_unavailable(
                    request
                ):
                    from creopdm.api.pages import render

                    return render(
                        request,
                        "site_unavailable.html",
                        {
                            "app_name": APP_NAME,
                            "app_version": APP_VERSION,
                        },
                    )

            return await call_next(request)
        finally:
            db.close()
            set_request_identity(None)

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="creopdm_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 24 * 14,
    )

    return app
