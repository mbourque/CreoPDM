"""Project lifecycle: create, list, open, delete. Git init is an implementation detail."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from creopdm.constants import (
    APP_NAME,
    APP_SCHEMA_VERSION,
    DEFAULT_BRANCH,
    PROJECT_JSON_NAME,
    PROJECT_MARKER_DIR,
    SCHEMA_VERSION_NAME,
    STANDARD_PROJECT_FOLDERS,
    ActivityAction,
    CheckoutStatus,
)
from creopdm.exceptions import (
    DuplicateProjectError,
    PathValidationError,
    ProjectNotFoundError,
    RepositoryError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.project import Project
from creopdm.services.activity_service import ActivityService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.paths import normalize_fs_path, validate_project_location

logger = get_logger("projects")

README_TEMPLATE = """# {name}

Managed by {app_name}.

Do not edit the `.git` directory. Use {app_name} to add files and record versions.
"""

GITIGNORE_TEMPLATE = """# Creo transients — not engineering objects
*.tst
*.err
*.inf
*.idx
*.acl
*.crc
trail.txt*
std.out
*.log
"""


class ProjectService:
    def __init__(
        self,
        git: GitService,
        locks: ProjectLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
    ) -> None:
        self._git = git
        self._locks = locks
        self._activities = activities
        self._users = users

    def list_projects(self, session: Session, include_inactive: bool = False) -> list[Project]:
        stmt = select(Project).order_by(Project.name.asc())
        if not include_inactive:
            stmt = stmt.where(Project.active.is_(True))
        return list(session.scalars(stmt))

    def get_project(self, session: Session, project_uuid: str) -> Project:
        project = session.scalar(select(Project).where(Project.uuid == project_uuid))
        if project is None or not project.active:
            raise ProjectNotFoundError(
                "Project not found.",
                details={"uuid": project_uuid},
            )
        return project

    def create_project(
        self,
        session: Session,
        name: str,
        repository_path: str,
        number: str | None = None,
        description: str | None = None,
    ) -> Project:
        if not name.strip():
            raise PathValidationError("A project name is required.")
        location = validate_project_location(repository_path)
        existing = session.scalar(
            select(Project).where(Project.repository_path == str(location), Project.active.is_(True))
        )
        if existing is not None:
            raise DuplicateProjectError(
                "A project already exists at this location.",
                details={"path": str(location)},
            )

        project_uuid = str(uuid.uuid4())
        user = self._users.get_current_user()
        now = datetime.now(timezone.utc)

        location.mkdir(parents=True, exist_ok=True)
        self._write_project_scaffold(location, project_uuid, name.strip(), number, description)

        if not self._git.is_available():
            raise RepositoryError("Git is required to create a project but was not found on PATH.")

        self._git.init_repository(location, DEFAULT_BRANCH)
        with self._locks.acquire(project_uuid):
            self._git.stage_files(
                location,
                [
                    PROJECT_MARKER_DIR,
                    *STANDARD_PROJECT_FOLDERS,
                    "README.md",
                    ".gitignore",
                ],
            )
            self._git.commit(
                location,
                f"Initialize project {name.strip()}",
                user,
            )

        project = Project(
            uuid=project_uuid,
            name=name.strip(),
            number=(number or "").strip() or None,
            description=(description or "").strip() or None,
            repository_path=str(location),
            default_branch=DEFAULT_BRANCH,
            created_at=now,
            updated_at=now,
            active=True,
        )
        session.add(project)
        session.flush()
        self._activities.record(
            session,
            ActivityAction.PROJECT_CREATED,
            user,
            project_id=project.id,
            details={"path": str(location), "name": project.name},
        )
        logger.info("Created project %s at %s", project.uuid, location)
        return project

    def delete_project(self, session: Session, project_uuid: str) -> None:
        """Soft-delete. Never delete repository files from disk."""
        project = self.get_project(session, project_uuid)
        project.active = False
        project.updated_at = datetime.now(timezone.utc)
        session.flush()
        logger.info("Deactivated project %s", project.uuid)

    def project_status(self, session: Session, project_uuid: str) -> dict[str, int | str]:
        project = self.get_project(session, project_uuid)
        objects = list(
            session.scalars(
                select(EngineeringObject).where(EngineeringObject.project_id == project.id)
            )
        )
        user = self._users.get_current_user()
        active = list(
            session.scalars(
                select(Checkout)
                .join(EngineeringObject, Checkout.object_id == EngineeringObject.id)
                .where(
                    EngineeringObject.project_id == project.id,
                    Checkout.status == CheckoutStatus.ACTIVE.value,
                )
            )
        )
        mine = sum(1 for row in active if row.user_name == user.user_name)
        counts: dict[str, int | str] = {
            "files": len(objects),
            "creo_parts": sum(1 for obj in objects if obj.object_type == "CREO_PART"),
            "assemblies": sum(1 for obj in objects if obj.object_type == "CREO_ASSEMBLY"),
            "drawings": sum(1 for obj in objects if obj.object_type == "CREO_DRAWING"),
            "documents": sum(
                1
                for obj in objects
                if obj.object_type in {"PDF", "DOCUMENT", "SPREADSHEET", "TEXT", "IMAGE"}
            ),
            "checked_out_by_me": mine,
            "checked_out_by_others": len(active) - mine,
            "modified_locally": 0,
            "out_of_date": 0,
            "untracked": 0,
        }
        return counts

    def _write_project_scaffold(
        self,
        location: Path,
        project_uuid: str,
        name: str,
        number: str | None,
        description: str | None,
    ) -> None:
        marker = location / PROJECT_MARKER_DIR
        marker.mkdir(parents=True, exist_ok=True)
        payload = {
            "uuid": project_uuid,
            "name": name,
            "number": number,
            "description": description,
            "default_branch": DEFAULT_BRANCH,
            "schema_version": APP_SCHEMA_VERSION,
            "tracked_parameters": [
                "PART_NUMBER",
                "DESCRIPTION",
                "MATERIAL",
                "DRAWN_BY",
            ],
        }
        (marker / PROJECT_JSON_NAME).write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        (marker / SCHEMA_VERSION_NAME).write_text(f"{APP_SCHEMA_VERSION}\n", encoding="utf-8")
        for folder in STANDARD_PROJECT_FOLDERS:
            folder_path = location / folder
            folder_path.mkdir(exist_ok=True)
            (folder_path / ".gitkeep").write_text("", encoding="utf-8")
        (location / "README.md").write_text(
            README_TEMPLATE.format(name=name, app_name=APP_NAME),
            encoding="utf-8",
        )
        (location / ".gitignore").write_text(GITIGNORE_TEMPLATE, encoding="utf-8")

    @staticmethod
    def repository_path(project: Project) -> Path:
        return normalize_fs_path(project.repository_path)
