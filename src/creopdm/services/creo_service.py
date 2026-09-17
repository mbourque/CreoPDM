"""Creo-facing operations used by the PDM UI. Isolated from connector technology."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from creopdm.creo.base import CreoConnector
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoUnavailableError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.classify import is_creo_openable, is_creo_view, is_extra_cad
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
        self._connector = connector
        self._objects = objects
        self._checkouts = checkouts
        self._workspaces = workspaces

    def set_connector(self, connector: CreoConnector) -> None:
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
        workdir = working_directory_for(path)
        models = self._workspaces._config.model_cad_extensions()
        extras = self._workspaces._config.extra_cad_extensions()
        all_cad = self._workspaces._cad_extensions()
        if is_extra_cad(path.name, extras, models):
            raise ValidationAppError(
                f"{path.name} cannot be opened. This file type is not opened by Creo.",
                details={"path": str(path), "filename": path.name},
            )
        is_model = obj.object_type.startswith("CREO_") or is_creo_openable(
            path.name, models, all_cad
        )
        view_object = is_creo_view(path.name)
        open_mode = self._connector.cad_open_mode()
        use_view = view_object or (open_mode == "view" and is_model)
        creo_object = (not use_view) and is_model
        logical = CreoFileManager.normalize_creo_filename(path.name, (*models, *all_cad))
        file_release = creo_release_for(path, path.name)
        if not file_release and obj.current_version is not None:
            file_release = obj.current_version.creo_release
        if launch:
            if use_view:
                method = self._open_view_path(path)
            elif creo_object and open_mode == "embedded":
                raise ValidationAppError(
                    "Open this model from Creo's built-in browser.",
                    details={"path": str(path), "filename": path.name},
                )
            else:
                method = self._open_path(path, creo_object=creo_object)
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
            "creo_release": file_release or "",
        }

    def _open_path(self, path: Path, creo_object: bool) -> str:
        if creo_object:
            try:
                self._connector.open_model(path)
                return "creo"
            except CreoUnavailableError:
                logger.info("Creo connector unavailable; falling back to the system opener")
        return self._open_with_shell(path)

    def _open_view_path(self, path: Path) -> str:
        try:
            self._connector.open_view(path)
            return "creo_view"
        except CreoUnavailableError:
            logger.info("Creo View connector unavailable; falling back to the system opener")
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
