"""Project lifecycle: create, list, open, delete. Git init is an implementation detail."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
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
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.activity import Activity
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.project import Project
from creopdm.models.remote import Remote
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.git_service import GitService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.utils.files import remove_file, remove_tree
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
*.acl
trail.txt*
std.out
std.err
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

    def update_project(
        self,
        session: Session,
        project_uuid: str,
        name: str,
        number: str | None = None,
        description: str | None = None,
    ) -> Project:
        project = self.get_project(session, project_uuid)
        new_name = name.strip()
        if not new_name:
            raise ValidationAppError("A project name is required.")
        new_number = (number or "").strip() or None
        new_description = (description or "").strip() or None
        user = self._users.get_current_user()
        repo = Path(project.repository_path)
        marker_rel = f"{PROJECT_MARKER_DIR}/{PROJECT_JSON_NAME}"
        with self._locks.acquire(project.uuid):
            captured = None
            try:
                captured = self._git.get_head(repo)
            except Exception:
                captured = None
            self._rewrite_project_marker(
                repo,
                project.uuid,
                new_name,
                new_number,
                new_description,
            )
            try:
                self._git.stage_files(repo, [marker_rel])
                if self._git.is_dirty(repo):
                    self._git.commit(repo, f"Rename project to {new_name}", user)
            except Exception as exc:
                if captured:
                    self._git.reset_to(repo, captured)
                raise RepositoryError(
                    "Could not record the project rename in the vault.",
                    details={"name": new_name},
                ) from exc
            old_name = project.name
            try:
                project.name = new_name
                project.number = new_number
                project.description = new_description
                project.updated_at = datetime.now(timezone.utc)
                session.flush()
                self._activities.record(
                    session,
                    ActivityAction.PROJECT_UPDATED,
                    user,
                    project_id=project.id,
                    details={"old_name": old_name, "name": new_name},
                )
            except Exception as exc:
                if captured:
                    self._git.reset_to(repo, captured)
                raise RepositoryError(
                    "The vault was updated but project metadata could not be saved. "
                    "The repository was restored.",
                    details={"name": new_name},
                ) from exc
        logger.info("Renamed project %s to %s", project.uuid, new_name)
        return project

    def delete_project(self, session: Session, project_uuid: str) -> None:
        """Hide the project in CreoPDM. Never delete repository files from disk."""
        project = self.get_project(session, project_uuid)
        project.active = False
        project.updated_at = datetime.now(timezone.utc)
        session.flush()
        logger.info("Deactivated project %s", project.uuid)

    def forget_project(
        self,
        session: Session,
        project_uuid: str,
        confirm_name: str,
        workspace_path: Path | None = None,
    ) -> dict[str, str]:
        """Unregister the project and strip Git metadata. CAD files stay on disk.

        Removes `.git`, Git ignore files, `.creopdm`, and CreoPDM workspace copies.
        Does not delete engineering files in the project folder.
        """
        project = self.get_project(session, project_uuid)
        expected = project.name.strip()
        if confirm_name.strip() != expected:
            raise ValidationAppError(
                "Type the project name exactly to forget it.",
                details={"name": expected},
            )
        repo = Path(project.repository_path)
        name = project.name
        warnings: list[str] = []
        with self._locks.acquire(project.uuid):
            self._strip_git_metadata(repo)
            if (repo / ".git").exists():
                warnings.append(
                    "Git metadata is still present because a program has the project folder open."
                )
            if workspace_path is not None and not remove_tree(workspace_path):
                warnings.append(
                    "The workspace folder is still open in another program (often File Explorer). "
                    "Close that window and delete the leftover workspace folder if you want it gone."
                )
            self._delete_project_records(session, project)
        logger.info("Forgot project %s at %s; engineering files were left in place", project_uuid, repo)
        return {
            "uuid": project_uuid,
            "name": name,
            "repository_path": str(repo),
            "warning": " ".join(warnings) if warnings else "",
        }

    def _strip_git_metadata(self, repo: Path) -> None:
        remove_tree(repo / ".git")
        for name in (".gitignore", ".gitattributes"):
            remove_file(repo / name)
        remove_tree(repo / PROJECT_MARKER_DIR)
        for folder in STANDARD_PROJECT_FOLDERS:
            remove_file(repo / folder / ".gitkeep")

    def _delete_project_records(self, session: Session, project: Project) -> None:
        objects = list(
            session.scalars(select(EngineeringObject).where(EngineeringObject.project_id == project.id))
        )
        object_ids = [item.id for item in objects]
        if object_ids:
            session.execute(
                update(EngineeringObject)
                .where(EngineeringObject.id.in_(object_ids))
                .values(current_version_id=None)
            )
            session.flush()
            session.execute(delete(Parameter).where(Parameter.object_id.in_(object_ids)))
            session.execute(delete(Checkout).where(Checkout.object_id.in_(object_ids)))
            session.execute(
                delete(Dependency).where(
                    or_(
                        Dependency.parent_object_id.in_(object_ids),
                        Dependency.child_object_id.in_(object_ids),
                    )
                )
            )
            session.execute(delete(Activity).where(Activity.object_id.in_(object_ids)))
            session.execute(delete(ObjectVersion).where(ObjectVersion.object_id.in_(object_ids)))
            session.execute(delete(EngineeringObject).where(EngineeringObject.id.in_(object_ids)))
        session.execute(delete(Dependency).where(Dependency.project_id == project.id))
        session.execute(delete(Activity).where(Activity.project_id == project.id))
        session.execute(delete(Remote).where(Remote.project_id == project.id))
        session.delete(project)
        session.flush()

    def preferred_import_directory(self, project: Project) -> Path:
        """Folder the Add Files dialog should start in: the original project folder."""
        return Path(project.repository_path)

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
        (location / "README.md").write_text(
            README_TEMPLATE.format(name=name, app_name=APP_NAME),
            encoding="utf-8",
        )
        (location / ".gitignore").write_text(GITIGNORE_TEMPLATE, encoding="utf-8")

    def _rewrite_project_marker(
        self,
        location: Path,
        project_uuid: str,
        name: str,
        number: str | None,
        description: str | None,
    ) -> None:
        marker = location / PROJECT_MARKER_DIR
        marker.mkdir(parents=True, exist_ok=True)
        path = marker / PROJECT_JSON_NAME
        payload: dict = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {}
        payload.update(
            {
                "uuid": project_uuid,
                "name": name,
                "number": number,
                "description": description,
                "default_branch": payload.get("default_branch") or DEFAULT_BRANCH,
                "schema_version": payload.get("schema_version") or APP_SCHEMA_VERSION,
            }
        )
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def repository_path(project: Project) -> Path:
        return normalize_fs_path(project.repository_path)
