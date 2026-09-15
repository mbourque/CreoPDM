"""Application service container. Wired once at startup and injected into routes."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from creopdm.config import AppSettings, ConfigManager
from creopdm.creo.base import CreoConnector
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkin_service import CheckinService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.creo_service import CreoService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.project_service import ProjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.storage.base import VersionStore
from creopdm.utils.identity import CurrentUserProvider


@dataclass
class AppContext:
    config: ConfigManager
    settings: AppSettings
    session_factory: sessionmaker[Session]
    git: GitService
    version_store: VersionStore
    users: CurrentUserProvider
    locks: ProjectLockManager
    creo: CreoConnector
    activities: ActivityService
    projects: ProjectService
    objects: ObjectService
    workspaces: WorkspaceService
    checkouts: CheckoutService
    checkins: CheckinService
    creo_service: CreoService
