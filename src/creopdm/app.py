"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from creopdm.api import checkout, creo, health, objects, pages, projects, settings
from creopdm.api.errors import register_error_handlers
from creopdm.config import ConfigManager
from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.context import AppContext
from creopdm.creo.connector_factory import create_creo_connector
from creopdm.database.migrate import run_migrations
from creopdm.database.session import create_db_engine, create_session_factory
from creopdm.logging_setup import get_logger, setup_logging
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkin_service import CheckinService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.creo_service import CreoService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.project_service import ProjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.storage.git_store import GitVersionStore
from creopdm.utils.identity import CurrentUserProvider

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
    identity = users or CurrentUserProvider()
    locks = ProjectLockManager()
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
    return AppContext(
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
        projects=ProjectService(git, locks, activities, identity, workspaces),
        objects=objects,
        workspaces=workspaces,
        checkouts=checkouts,
        checkins=checkins,
        creo_service=CreoService(creo_connector, objects, checkouts, workspaces),
    )


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
    app.include_router(health.router)
    app.include_router(settings.router)
    app.include_router(projects.router)
    app.include_router(objects.router)
    app.include_router(checkout.router)
    app.include_router(creo.router)
    app.include_router(pages.router)
    static_dir = PACKAGE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
