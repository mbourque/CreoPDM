"""Creo-facing operations used by the PDM UI. Isolated from connector technology."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.orm import Session

from creopdm.creo.base import CreoConnector
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoUnavailableError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.project import Project
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.classify import classify_filename, is_creo_openable, is_creo_view
from creopdm.utils.creo_header import creo_release_for
from creopdm.utils.launch import open_windows_file, working_directory_for

logger = get_logger("creo-service")


class CreoService:
    def __init__(
        self,
        connector: CreoConnector,
        objects: ObjectService,
        checkouts: CheckoutService,
        workspaces: WorkspaceService,
    ) -> None:
        self._objects = objects
        self._checkouts = checkouts
        self._workspaces = workspaces
        self._connector = connector

    def open_object(self, session: Session, object_uuid: str, launch: bool = True) -> dict[str, str | bool]:
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        checkout = self._checkouts.active_for(session, obj.id)
        view = self._checkouts.describe(obj, checkout)
        if checkout is None:
            try:
                latest = self._workspaces.locate_content(project.uuid, obj)
                if self._workspaces.is_modified(project, obj):
                    path = latest
                else:
                    path = self._workspaces.materialize(
                        project,
                        obj,
                        writable=False,
                        overwrite_modified=True,
                    )
            except PathValidationError:
                path = self._workspaces.materialize(
                    project,
                    obj,
                    writable=False,
                    overwrite_modified=True,
                )
        else:
            try:
                path = self._workspaces.locate_content(project.uuid, obj)
            except PathValidationError:
                path = self._workspaces.materialize(
                    project,
                    obj,
                    writable=view.owned_by_me,
                    overwrite_modified=False,
                )
        file_release = creo_release_for(path, path.name)
        if not file_release and obj.current_version is not None:
            file_release = obj.current_version.creo_release
        return self._open_resolved(
            path,
            launch=launch,
            object_type=obj.object_type,
            creo_release=file_release or "",
            browser_url=f"/api/objects/{object_uuid}/content",
        )

    def open_workspace_file(self, project: Project, relative_path: str, launch: bool = True) -> dict[str, str | bool]:
        path = self._workspaces.file_path(project.uuid, relative_path)
        if not path.is_file():
            raise PathValidationError(
                f"Workspace file not found: {Path(relative_path).name}.",
                details={"relative_path": relative_path},
            )
        kind = classify_filename(
            path.name,
            extra_cad_extensions=self._workspaces._config.data_cad_extensions(),
            model_extensions=self._workspaces._config.model_cad_extensions(),
            document_extensions=self._workspaces._config.document_extensions(),
        )
        rel = str(relative_path).replace("\\", "/")
        return self._open_resolved(
            path,
            launch=launch,
            object_type=kind.value,
            creo_release=creo_release_for(path, path.name) or "",
            browser_url=f"/api/projects/{project.uuid}/workspace/content?path={quote(rel)}",
        )

    def _open_resolved(
        self,
        path: Path,
        *,
        launch: bool,
        object_type: str = "",
        creo_release: str = "",
        browser_url: str = "",
    ) -> dict[str, str | bool | None]:
        workdir = working_directory_for(path)
        models = self._workspaces._config.model_cad_extensions()
        all_cad = self._workspaces._cad_extensions()
        is_model = object_type.startswith("CREO_") or is_creo_openable(
            path.name, models, all_cad
        )
        view_object = is_creo_view(path.name)
        open_mode = self._connector.cad_open_mode()
        use_view = view_object or (open_mode == "view" and is_model)
        creo_object = (not use_view) and is_model
        logical = CreoFileManager.normalize_creo_filename(path.name, (*models, *all_cad))
        url: str | None = None
        if launch:
            if not creo_object and not use_view:
                # Images, PDFs, docs, extra CAD — let the browser open locally.
                method = "browser"
                url = browser_url
            elif use_view:
                method = self._open_view_path(path, browser_url=browser_url)
                if method == "browser":
                    url = browser_url
            elif open_mode == "embedded":
                raise ValidationAppError(
                    "Open this model from Creo's built-in browser.",
                    details={"path": str(path), "filename": path.name},
                )
            elif open_mode == "association":
                method = "browser"
                url = browser_url
            else:
                method = self._open_path(path, browser_url=browser_url)
                if method == "browser":
                    url = browser_url
            logger.info("Opened %s via %s from %s", path, method, workdir)
        else:
            method = "prepared"
            logger.info("Prepared %s for Creo session open from %s", path, workdir)
        return {
            "path": str(path),
            "method": method,
            "filename": logical,
            "working_directory": str(workdir),
            "creo_object": creo_object,
            "creo_release": creo_release or "",
            "url": url,
        }

    def _open_path(self, path: Path, *, browser_url: str = "") -> str:
        try:
            self._connector.open_model(path)
            return "creo"
        except CreoUnavailableError:
            logger.info("Creo connector unavailable; opening in the browser instead")
            if browser_url:
                return "browser"
            return self._open_with_shell(path)

    def _open_view_path(self, path: Path, *, browser_url: str = "") -> str:
        try:
            self._connector.open_view(path)
            return "creo_view"
        except CreoUnavailableError:
            logger.info("Creo View connector unavailable; opening in the browser instead")
            if browser_url:
                return "browser"
            return self._open_with_shell(path)

    @staticmethod
    def _open_with_shell(path: Path) -> str:
        if os.name == "nt":
            try:
                open_windows_file(path, cwd=working_directory_for(path))
            except OSError as exc:
                logger.exception("Windows could not open %s", path)
                raise CreoUnavailableError(
                    f"Windows could not open {path.name}.",
                    details={"path": str(path), "reason": str(exc)},
                ) from exc
            return "shell"
        opener = "xdg-open" if os.name == "posix" else "open"
        result = subprocess.run(
            [opener, str(path)],
            check=False,
            capture_output=True,
            shell=False,
        )
        if result.returncode != 0:
            raise CreoUnavailableError(
                "Unable to open the file with the system viewer.",
                details={"path": str(path)},
            )
        return "shell"
