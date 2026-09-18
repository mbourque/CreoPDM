"""Project lifecycle: create, list, open, delete. Git init is an implementation detail."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from creopdm.constants import (
    DEFAULT_BRANCH,
    PROJECT_JSON_NAME,
    PROJECT_MARKER_DIR,
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
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.files import remove_tree
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.classify import matches_cad_models, matches_document
from creopdm.utils.native_dialog import default_project_location_start

logger = get_logger("projects")


class ProjectService:
    def __init__(
        self,
        git: GitService,
        locks: ProjectLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
        workspaces: WorkspaceService,
    ) -> None:
        self._git = git
        self._locks = locks
        self._activities = activities
        self._users = users
        self._workspaces = workspaces

    def list_projects(self, session: Session, include_inactive: bool = False) -> list[Project]:
        stmt = select(Project).order_by(Project.name.asc())
        if not include_inactive:
            stmt = stmt.where(Project.active.is_(True))
        return list(session.scalars(stmt))

    def _load_project(self, session: Session, project_uuid: str) -> Project:
        project = session.scalar(select(Project).where(Project.uuid == project_uuid))
        if project is None or not project.active:
            raise ProjectNotFoundError(
                "Project not found.",
                details={"uuid": project_uuid},
            )
        return project

    def get_project(self, session: Session, project_uuid: str) -> Project:
        project = self._load_project(session, project_uuid)
        self._workspaces.ensure_vault(project)
        return project

    def _require_unique_name(
        self,
        session: Session,
        name: str,
        *,
        exclude_uuid: str | None = None,
    ) -> None:
        wanted = name.strip().casefold()
        stmt = select(Project).where(Project.active.is_(True))
        for existing in session.scalars(stmt):
            if exclude_uuid and existing.uuid == exclude_uuid:
                continue
            if existing.name.strip().casefold() == wanted:
                raise DuplicateProjectError(
                    f'A project named "{existing.name}" already exists.',
                    details={"name": existing.name},
                )

    def create_project(
        self,
        session: Session,
        name: str,
        number: str | None = None,
        description: str | None = None,
    ) -> Project:
        if not name.strip():
            raise PathValidationError("A project name is required.")
        self._require_unique_name(session, name)

        project_uuid = str(uuid.uuid4())
        user = self._users.get_current_user()
        now = datetime.now(timezone.utc)

        if not self._git.is_available():
            raise RepositoryError("Git is required to create a project but was not found on PATH.")

        with self._locks.acquire(project_uuid):
            vault = self._workspaces.init_vault(project_uuid, name.strip(), user)

        project = Project(
            uuid=project_uuid,
            name=name.strip(),
            number=(number or "").strip() or None,
            description=(description or "").strip() or None,
            repository_path="",
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
            details={"workspace": str(vault), "name": project.name},
        )
        logger.info("Created project %s in workspace %s", project.uuid, vault)
        session.commit()
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
        self._require_unique_name(session, new_name, exclude_uuid=project.uuid)
        new_number = (number or "").strip() or None
        new_description = (description or "").strip() or None
        user = self._users.get_current_user()
        vault = self._workspaces.ensure_vault(project)
        marker_rel = f"{PROJECT_MARKER_DIR}/{PROJECT_JSON_NAME}"
        with self._locks.acquire(project.uuid):
            captured = None
            try:
                captured = self._git.get_head(vault)
            except Exception:
                captured = None
            self._workspaces.write_project_marker(project, new_name, new_number, new_description)
            try:
                self._git.stage_files(vault, [marker_rel])
                if self._git.is_dirty(vault):
                    self._git.commit(vault, f"Rename project to {new_name}", user)
            except Exception as exc:
                if captured:
                    self._git.reset_to(vault, captured)
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
                    self._git.reset_to(vault, captured)
                raise RepositoryError(
                    "The vault was updated but project metadata could not be saved. "
                    "The repository was restored.",
                    details={"name": new_name},
                ) from exc
        logger.info("Renamed project %s to %s", project.uuid, new_name)
        session.commit()
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
        """Unregister the project and delete the workspace Git vault."""
        project = self._load_project(session, project_uuid)
        expected = project.name.strip()
        if confirm_name.strip() != expected:
            raise ValidationAppError(
                "Type the project name exactly to forget it.",
                details={"name": expected},
            )
        leftover = self._workspaces.leftover_source(project)
        name = project.name
        warnings: list[str] = []
        with self._locks.acquire(project.uuid):
            if leftover is not None:
                self._workspaces.strip_location_git(leftover)
                if (leftover / ".git").exists():
                    warnings.append(
                        "Git metadata is still present because a program has the old project folder open."
                    )
            if workspace_path is not None and not remove_tree(workspace_path):
                warnings.append(
                    "The workspace folder is still open in another program (often File Explorer). "
                    "Close that window and delete the leftover workspace folder if you want it gone."
                )
            self._delete_project_records(session, project)
        logger.info("Forgot project %s", project_uuid)
        session.commit()
        return {
            "uuid": project_uuid,
            "name": name,
            "repository_path": str(leftover) if leftover is not None else "",
            "warning": " ".join(warnings) if warnings else "",
        }

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
        """Folder the Add Files dialog should start in."""
        leftover = self._workspaces.leftover_source(project)
        if leftover is not None and leftover.is_dir():
            return leftover
        return default_project_location_start()

    def project_status(
        self,
        session: Session,
        project_uuid: str,
        objects: list | None = None,
        project: Project | None = None,
    ) -> dict[str, int | str]:
        project = project or self.get_project(session, project_uuid)
        if objects is None:
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
        models = self._workspaces._config.cad_models_extensions()
        documents = self._workspaces._config.document_extensions()
        counts: dict[str, int | str] = {
            "files": len(objects),
            "cad_models": sum(
                1 for obj in objects if matches_cad_models(obj.filename, models, obj.extension)
            ),
            "creo_parts": sum(1 for obj in objects if obj.object_type == "CREO_PART"),
            "assemblies": sum(1 for obj in objects if obj.object_type == "CREO_ASSEMBLY"),
            "drawings": sum(1 for obj in objects if obj.object_type == "CREO_DRAWING"),
            "documents": sum(
                1 for obj in objects if matches_document(obj.filename, documents, obj.extension)
            ),
            "other": sum(
                1
                for obj in objects
                if not matches_cad_models(obj.filename, models, obj.extension)
            ),
            "checked_out": len(active),
            "checked_out_by_me": mine,
            "checked_out_by_others": len(active) - mine,
            "modified_locally": 0,
            "out_of_date": 0,
            "untracked": 0,
        }
        return counts
