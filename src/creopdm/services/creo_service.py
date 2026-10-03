"""Creo-facing operations used by the PDM UI. Isolated from connector technology."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import DependencyType
from creopdm.creo.base import CreoConnector
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoUnavailableError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.classify import classify_filename, is_creo_js_openable, is_creo_openable, is_creo_view
from creopdm.utils.creo_dependencies import (
    collect_open_dependency_objects,
    needs_open_dependencies,
)
from creopdm.utils.creo_header import creo_release_for, is_creo_native_model
from creopdm.utils.launch import working_directory_for

logger = get_logger("creo-service")

# Edges that mean "parent needs this child on disk to Retrieve".
_OPEN_DEPENDENCY_TYPES = frozenset(
    {
        DependencyType.ASSEMBLY_MEMBER.value,
        DependencyType.DRAWING_MODEL.value,
        DependencyType.REFERENCE.value,
        DependencyType.SKELETON.value,
        DependencyType.MERGE.value,
        DependencyType.UNKNOWN.value,
    }
)
_MAX_DEP_DEPENDENCY_DEPTH = 12
_MAX_DEP_DEPENDENCIES = 2500


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
        include_dependencies: bool = True,
    ) -> dict:
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        checkout = self._checkouts.active_for(session, obj.id)
        view = self._checkouts.describe(obj, checkout)
        if checkout is None:
            try:
                latest = self._workspaces.locate_content(product, obj)
                if self._workspaces.is_modified(product, obj):
                    path = latest
                else:
                    path = self._workspaces.materialize(
                        product,
                        obj,
                        writable=False,
                        overwrite_modified=True,
                    )
            except PathValidationError:
                path = self._workspaces.materialize(
                    product,
                    obj,
                    writable=False,
                    overwrite_modified=True,
                )
        else:
            try:
                path = self._workspaces.locate_content(product, obj)
            except PathValidationError:
                path = self._workspaces.materialize(
                    product,
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
        dependencies: list[dict[str, str | None]] = []
        if include_dependencies:
            dependencies = self._dependencies_for(
                session,
                product,
                path=path,
                object_type=obj.object_type,
                relative_path=obj.relative_path,
                filename=obj.filename,
                skip_object_id=obj.id,
            )
        version = obj.current_version
        payload = self._open_resolved(
            path,
            launch=launch,
            object_type=obj.object_type,
            creo_release=file_release or "",
            browser_url=f"/api/objects/{object_uuid}/content",
            object_id=object_uuid,
            product_id=str(product.uuid),
            relative_path=obj.relative_path,
            content_hash=(version.content_hash if version is not None else "") or "",
            file_size=int(version.file_size) if version is not None else 0,
            dependencies=dependencies,
        )
        # Not checked out to me: align local cache to vault tip (drop higher .N leftovers).
        # Checked out to me: keep local newer Creo saves for check-in.
        payload["replace_newer"] = not view.owned_by_me
        return payload

    def open_workspace_file(
        self,
        session: Session,
        product: Product,
        relative_path: str,
        launch: bool = True,
        include_dependencies: bool = True,
    ) -> dict:
        path = self._workspaces.file_path(product, relative_path)
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
        dependencies: list[dict[str, str | None]] = []
        if include_dependencies:
            dependencies = self._dependencies_for(
                session,
                product,
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
            browser_url=f"/api/products/{product.uuid}/workspace/content?path={quote(rel)}",
            product_id=str(product.uuid),
            relative_path=rel,
            dependencies=dependencies,
        )

    def _where_used_dependency_objects(
        self,
        session: Session,
        product_id: int,
        root_object_id: int,
    ) -> list[EngineeringObject]:
        """Full member tree from Where Used edges (any folder)."""
        has_edge = session.scalar(
            select(Dependency.id)
            .where(
                Dependency.product_id == product_id,
                Dependency.parent_object_id == root_object_id,
                Dependency.dependency_type.in_(_OPEN_DEPENDENCY_TYPES),
            )
            .limit(1)
        )
        if has_edge is None:
            return []
        queue: list[tuple[int, int]] = [(root_object_id, 0)]
        seen_parents = {root_object_id}
        found: dict[int, EngineeringObject] = {}
        while queue and len(found) < _MAX_DEP_DEPENDENCIES:
            parent_id, depth = queue.pop(0)
            if depth >= _MAX_DEP_DEPENDENCY_DEPTH:
                continue
            edges = session.scalars(
                select(Dependency).where(
                    Dependency.product_id == product_id,
                    Dependency.parent_object_id == parent_id,
                    Dependency.dependency_type.in_(_OPEN_DEPENDENCY_TYPES),
                )
            ).all()
            child_ids = [
                edge.child_object_id
                for edge in edges
                if edge.child_object_id not in found and edge.child_object_id != root_object_id
            ]
            if not child_ids:
                continue
            children = session.scalars(
                select(EngineeringObject)
                .options(joinedload(EngineeringObject.current_version))
                .where(EngineeringObject.id.in_(child_ids))
            ).unique().all()
            for child in children:
                if child.id in found:
                    continue
                found[child.id] = child
                if len(found) >= _MAX_DEP_DEPENDENCIES:
                    break
                if needs_open_dependencies(child.object_type, child.filename) and child.id not in seen_parents:
                    seen_parents.add(child.id)
                    queue.append((child.id, depth + 1))
        return list(found.values())

    def _dependencies_for(
        self,
        session: Session,
        product: Product,
        *,
        path: Path,
        object_type: str,
        relative_path: str,
        filename: str,
        skip_object_id: int | None,
    ) -> list[dict[str, str | None]]:
        if not needs_open_dependencies(object_type, filename):
            return []
        models = self._workspaces._config.model_cad_extensions()
        all_cad = self._workspaces._cad_extensions()
        siblings = self._objects.list_objects(session, product.id)
        root_id = skip_object_id
        if root_id is None:
            rel_key = str(relative_path or "").replace("\\", "/").lower()
            for row in siblings:
                if str(getattr(row, "relative_path", "") or "").replace("\\", "/").lower() == rel_key:
                    root_id = int(row.id)
                    break

        # Prefer the Where Used dependency table when this model already has
        # edges (fast reopen). Fall back to a vault byte-scan walk only when
        # nothing is indexed yet — do not rescan every open when DB knows it.
        source = "where-used"
        chosen: list[EngineeringObject] = []
        if root_id is not None:
            chosen = self._where_used_dependency_objects(session, product.id, root_id)

        if not chosen:
            source = "vault-scan"

            def _resolve(obj: object) -> Path | None:
                try:
                    return self._workspaces.locate_content(product, obj)  # type: ignore[arg-type]
                except PathValidationError:
                    try:
                        return self._workspaces.materialize(
                            product,
                            obj,  # type: ignore[arg-type]
                            writable=False,
                            overwrite_modified=True,
                        )
                    except Exception:  # noqa: BLE001
                        return None

            chosen = collect_open_dependency_objects(
                primary_relative=relative_path,
                primary_filename=filename,
                object_type=object_type,
                siblings=siblings,
                model_path=path,
                model_extensions=models,
                all_cad_extensions=all_cad,
                resolve_path=_resolve,
                skip_object_id=root_id if root_id is not None else skip_object_id,
            )

        out: list[dict[str, str | None]] = []
        for obj in chosen:
            if skip_object_id is not None and obj.id == skip_object_id:
                continue
            try:
                dep_path = self._workspaces.locate_content(product, obj)
            except PathValidationError:
                dep_path = self._workspaces.materialize(
                    product,
                    obj,
                    writable=False,
                    overwrite_modified=True,
                )
            if not dep_path.is_file():
                continue
            logical = CreoFileManager.normalize_creo_filename(
                dep_path.name, (*models, *all_cad)
            )
            version = getattr(obj, "current_version", None)
            out.append(
                {
                    "object_id": str(obj.uuid),
                    "product_id": str(product.uuid),
                    "relative_path": str(obj.relative_path).replace("\\", "/"),
                    "filename": logical,
                    "disk_name": CreoFileManager.workspace_materialize_name(
                        dep_path.name, (*models, *all_cad)
                    ),
                    "content_hash": (version.content_hash if version is not None else "") or "",
                    "file_size": int(version.file_size) if version is not None else 0,
                }
            )
        if out:
            logger.info(
                "Prepared %s open dependencies for %s (%s)",
                len(out),
                Path(filename).name,
                source,
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
        product_id: str = "",
        relative_path: str = "",
        content_hash: str = "",
        file_size: int = 0,
        dependencies: list[dict[str, str | None]] | None = None,
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
            "disk_name": CreoFileManager.workspace_materialize_name(
                path.name, (*models, *all_cad)
            ),
            "working_directory": str(workdir.resolve()),
            "object_id": object_id or None,
            "product_id": product_id or None,
            "relative_path": relative_path or None,
            "content_hash": content_hash or None,
            "file_size": int(file_size or 0) or None,
            "creo_object": creo_object,
            "open_with_creo": open_with_creo,
            "requires_agent_cache": requires_agent_cache,
            "creo_release": creo_release or "",
            "url": url,
            "dependencies": dependencies or [],
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
