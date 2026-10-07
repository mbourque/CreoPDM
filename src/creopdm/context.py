"""Application service container. Wired once at startup and injected into routes."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from creopdm.config import AppSettings, ConfigManager
from creopdm.creo.base import CreoConnector
from creopdm.services.activity_service import ActivityService
from creopdm.services.ai_snapshot_service import AiSnapshotService
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
from creopdm.services.workspace_service import WorkspaceService
from creopdm.services.zip_import_jobs import ZipImportJobs
from creopdm.storage.base import VersionStore
from creopdm.utils.identity import CurrentUserProvider


@dataclass
class AppContext:
    config: ConfigManager
    settings: AppSettings
    engine: Engine
    session_factory: sessionmaker[Session]
    git: GitService
    version_store: VersionStore
    users: CurrentUserProvider
    locks: ProductLockManager
    creo: CreoConnector
    activities: ActivityService
    products: ProductService
    objects: ObjectService
    workspaces: WorkspaceService
    checkouts: CheckoutService
    checkins: CheckinService
    creo_service: CreoService
    metadata: MetadataService
    ai_snapshots: AiSnapshotService
    where_used_index: WhereUsedIndexJobs
    zip_imports: ZipImportJobs
    email: EmailService
    notifications: NotificationService
    product_watches: ProductWatchService
    password_resets: PasswordResetService
    user_accounts: UserService = field(default_factory=UserService)
    # When False (tests with StaticUserProvider), skip login redirects.
    auth_enabled: bool = True
