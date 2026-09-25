"""Creo-facing operations used by the PDM UI. Isolated from connector technology."""

from __future__ import annotations

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
from creopdm.utils.classify import classify_filename, is_creo_js_openable, is_creo_openable, is_creo_view
from creopdm.utils.creo_companions import needs_open_companions, select_companion_objects
from creopdm.utils.creo_header import creo_release_for, is_creo_native_model
from creopdm.utils.launch import working_directory_for

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

    def set_connector(self, connector: CreoConnector) -> None:
        self._connector = connector

    def open_object(
        self,
        session: Session,
        object_uuid: str,
        launch: bool = True,
        include_companions: bool = True,
    ) -> dict:
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        checkout = self._checkouts.active_for(session, obj.id)
        view = self._checkouts.describe(obj, checkout)
        if checkout is None:
            try:
                latest = self._workspaces.locate_content(project, obj)
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
                path = self._workspaces.locate_content(project, obj)
            except PathValidationError:
                path = self._workspaces.materialize(
                    project,
                    obj,
                    writable=view.owned_by_me,
                    overwrite_modified=False,
                )
        # Version gating is only for native Creo .prt/.asm/.drw. Other Creo-openable
        # formats (STEP, SolidWorks, …) have no Creo save release to compare.
        file_release = ""
        if is_creo_native_model(path.name):
            file_release = creo_release_for(path, path.name) or ""
            if not file_release and obj.current_version is not None:
                file_release = obj.current_version.creo_release or ""
        companions: list[dict[str, str | None]] = []
        if include_companions:
            companions = self._companions_for(
                session,
                project,
                path=path,
                object_type=obj.object_type,
                relative_path=obj.relative_path,
                filename=obj.filename,
                skip_object_id=obj.id,
            )
        return self._open_resolved(
            path,
            launch=launch,
            object_type=obj.object_type,
            creo_release=file_release or "",
            browser_url=f"/api/objects/{object_uuid}/content",
            object_id=object_uuid,
            project_id=str(project.uuid),
            relative_path=obj.relative_path,
            companions=companions,
        )

    def open_workspace_file(
        self,
        session: Session,
        project: Project,
        relative_path: str,
        launch: bool = True,
        include_companions: bool = True,
    ) -> dict:
        path = self._workspaces.file_path(project, relative_path)
        if not path.is_file():
            raise PathValidationError(
                f"Vault file not found: {Path(relative_path).name}.",
                details={"relative_path": relative_path},
            )
        kind = classify_filename(
            path.name,
            extra_cad_extensions=self._workspaces._config.data_cad_extensions(),
            model_extensions=self._workspaces._config.model_cad_extensions(),
            document_extensions=self._workspaces._config.document_extensions(),
        )
        rel = str(relative_path).replace("\\", "/")
        companions: list[dict[str, str | None]] = []
        if include_companions:
            companions = self._companions_for(
                session,
                project,
                path=path,
                object_type=kind.value,
                relative_path=rel,
                filename=path.name,
                skip_object_id=None,
            )
        release = ""
        if is_creo_native_model(path.name):
            release = creo_release_for(path, path.name) or ""
        return self._open_resolved(
            path,
            launch=launch,
            object_type=kind.value,
            creo_release=release,
            browser_url=f"/api/projects/{project.uuid}/workspace/content?path={quote(rel)}",
            project_id=str(project.uuid),
            relative_path=rel,
            companions=companions,
        )

    def _companions_for(
        self,
        session: Session,
        project: Project,
        *,
        path: Path,
        object_type: str,
        relative_path: str,
        filename: str,
        skip_object_id: int | None,
    ) -> list[dict[str, str | None]]:
        if not needs_open_companions(object_type, filename):
            return []
        models = self._workspaces._config.model_cad_extensions()
        all_cad = self._workspaces._cad_extensions()
        siblings = self._objects.list_objects(session, project.id)
        chosen = select_companion_objects(
            primary_relative=relative_path,
            primary_filename=filename,
            object_type=object_type,
            siblings=siblings,
            model_path=path,
            model_extensions=models,
            all_cad_extensions=all_cad,
        )
        out: list[dict[str, str | None]] = []
        for obj in chosen:
            if skip_object_id is not None and obj.id == skip_object_id:
                continue
            try:
                companion_path = self._workspaces.locate_content(project, obj)
            except PathValidationError:
                companion_path = self._workspaces.materialize(
                    project,
                    obj,
                    writable=False,
                    overwrite_modified=True,
                )
            if not companion_path.is_file():
                continue
            logical = CreoFileManager.normalize_creo_filename(
                companion_path.name, (*models, *all_cad)
            )
            out.append(
                {
                    "object_id": str(obj.uuid),
                    "project_id": str(project.uuid),
                    "relative_path": str(obj.relative_path).replace("\\", "/"),
                    "filename": logical,
                    "disk_name": companion_path.name,
                }
            )
        if out:
            logger.info(
                "Prepared %s open companions for %s",
                len(out),
                Path(filename).name,
            )
        return out

    def _open_resolved(
        self,
        path: Path,
        *,
        launch: bool,
        object_type: str = "",
        creo_release: str = "",
        browser_url: str = "",
        object_id: str = "",
        project_id: str = "",
        relative_path: str = "",
        companions: list[dict[str, str | None]] | None = None,
    ) -> dict:
        workdir = working_directory_for(path)
        models = self._workspaces._config.model_cad_extensions()
        all_cad = self._workspaces._cad_extensions()
        is_model = object_type.startswith("CREO_") or is_creo_openable(
            path.name, models, all_cad
        )
        view_object = is_creo_view(path.name)
        open_mode = self._connector.cad_open_mode()
        use_view = view_object or (open_mode == "view" and is_model)
        # Multi-CAD (SolidWorks, CATIA, …) is Creo-openable in File > Open, but
        # Creo.JS ModelDescriptor cannot open it — agent launches Parametric instead.
        js_openable = is_creo_js_openable(path.name, models, all_cad)
        creo_object = (not use_view) and is_model and js_openable
        # True when the agent should start parametric.exe with this file (Unite).
        open_with_creo = (not use_view) and is_model and not js_openable
        # Embedded Creo browser must fetch every Creo-openable model into the agent cache.
        requires_agent_cache = bool(is_model and not use_view)
        logical = CreoFileManager.normalize_creo_filename(path.name, (*models, *all_cad))
        url: str | None = None
        if launch:
            if not creo_object and not use_view:
                method, url = "browser", browser_url
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
                method, url = "browser", browser_url
            else:
                method = self._open_path(path, browser_url=browser_url)
                if method == "browser":
                    url = browser_url
            logger.info("Opened %s via %s from %s", path, method, workdir)
        else:
            method = "prepared"
            if not path.is_file():
                raise PathValidationError(
                    f"Vault file not found for Creo open: {path.name}.",
                    details={"path": str(path)},
                )
            logger.info("Prepared %s for Creo session open from %s", path, workdir)
        return {
            "path": str(path.resolve()),
            "method": method,
            "filename": logical,
            "disk_name": path.name,
            "working_directory": str(workdir.resolve()),
            "object_id": object_id or None,
            "project_id": project_id or None,
            "relative_path": relative_path or None,
            "creo_object": creo_object,
            "open_with_creo": open_with_creo,
            "requires_agent_cache": requires_agent_cache,
            "creo_release": creo_release or "",
            "url": url,
            "companions": companions or [],
        }

    def _open_path(self, path: Path, *, browser_url: str = "") -> str:
        try:
            self._connector.open_model(path)
            return "creo"
        except CreoUnavailableError:
            if browser_url:
                return "browser"
            raise

    def _open_view_path(self, path: Path, *, browser_url: str = "") -> str:
        try:
            self._connector.open_view(path)
            return "creo_view"
        except CreoUnavailableError:
            if browser_url:
                return "browser"
            raise
