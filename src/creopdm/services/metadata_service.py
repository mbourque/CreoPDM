"""Persist Creo.JS identity, parameters, materials, BOM, and dependency graph."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, aliased

from creopdm.constants import DependencyType
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import ObjectNotFoundError, PathValidationError, ValidationAppError
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.version import ObjectVersion
from creopdm.product_state import ensure_product_mutable
from creopdm.schemas.common import (
    CreoDependencyPayload,
    CreoMetadataRequest,
    CreoMetadataResponse,
    CreoParamPayload,
    RebuildWhereUsedResponse,
    WhereUsedItem,
    WhereUsedResponse,
)
from creopdm.services.object_service import ObjectService
from creopdm.utils.creo_dependencies import (
    model_references_filename,
    needs_open_dependencies,
    _MAX_WHERE_USED_ASM_PARENTS,
    _TOP_LEVEL_STEM_OMIT,
    _WHERE_USED_SCAN_LIMIT,
    _WHERE_USED_STEM_BLOCKLIST,
    read_model_scan_blob,
)
from creopdm.utils.creo_model_class import normalize_creo_identity
from creopdm.utils.bom_match import bom_lookup_keys, bom_where_used_keys
from creopdm.utils.classify import display_type_label
from creopdm.utils.cad_name_matcher import CadNameMatcher

logger = logging.getLogger(__name__)

_DRAWING_PARENT = "CREO_DRAWING"
_ASSEMBLY_TYPE = "CREO_ASSEMBLY"
# FeatSubType placeholders — not model-tree names (Round→ROUND, Chamfer→CHAMFER).
_GENERIC_FEATURE_NAME_LABELS = frozenset({"general", "none", "default", "edge"})


def normalize_feature_rows(features: Any) -> list[dict[str, Any]]:
    """Replace subtype placeholders used as Name; keep real Creo feature.name values."""
    if not isinstance(features, list):
        return []
    out: list[dict[str, Any]] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        row = dict(feat)
        name = str(row.get("name") or "").strip()
        typ = str(row.get("type") or "").strip()
        sub = str(row.get("subtype") or "").strip()
        # Name===Subtype (Edge/Edge) is the subtype column, not a rename.
        if name and sub and name.lower() == sub.lower():
            name = ""
        if name.lower() in _GENERIC_FEATURE_NAME_LABELS:
            name = ""
        if not name:
            if sub and sub.lower() not in _GENERIC_FEATURE_NAME_LABELS:
                name = sub
            elif typ:
                name = typ
            else:
                name = sub
        row["name"] = name
        out.append(row)
    return out


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class MetadataService:
    def __init__(self, objects: ObjectService, workspaces: Any | None = None) -> None:
        self._objects = objects
        self._workspaces = workspaces

    def save(
        self,
        session: Session,
        object_uuid: str,
        payload: CreoMetadataRequest,
    ) -> CreoMetadataResponse:
        obj = self._objects.get_object(session, object_uuid)
        ensure_product_mutable(obj.product, action="update metadata")
        version = self._resolve_version(session, obj, payload.version_id)
        if version is None:
            raise ValidationAppError(
                "This file has no version to attach Creo metadata to.",
                details={"object_id": object_uuid},
            )

        bom_payload = payload.bom
        if bom_payload is not None:
            if hasattr(bom_payload, "model_dump"):
                bom_payload = bom_payload.model_dump()
            elif isinstance(bom_payload, list):
                bom_payload = [
                    item.model_dump() if hasattr(item, "model_dump") else item for item in bom_payload
                ]

        # Collect / full snapshot posts send materials (even if empty). Erase this
        # object's Parameter + Dependency rows first, then write — never other objects.
        is_snapshot = (
            payload.materials is not None
            or bom_payload is not None
            or payload.features is not None
            or payload.units is not None
        )
        self._erase_object_metadata_tables(
            session,
            obj,
            version,
            clear_parameters=is_snapshot or bool(payload.parameters),
            clear_dependencies=is_snapshot or bool(payload.dependencies) or bom_payload is not None,
        )

        stored_identity: dict[str, Any] | None = None
        if payload.identity is not None:
            identity = dict(payload.identity)
            normalize_creo_identity(identity)
            previous = _loads(version.identity_json)
            # Assembly Collect flags the child first; a later part snapshot of SOLID
            # must not wipe SKELETON (Files Type flashes then reverts to Part).
            if self._keep_part_skeleton_role(obj, previous, identity):
                identity["model_type"] = "PART"
                identity["model_role"] = DependencyType.SKELETON.value
                normalize_creo_identity(identity)
            version.identity_json = _dumps(identity)
            stored_identity = identity
            common = str(identity.get("common_name") or "").strip()
            if common and (not obj.name or obj.name == obj.filename):
                obj.name = common[:255]

        if payload.materials is not None:
            version.materials_json = _dumps(payload.materials)

        if payload.units is not None:
            version.units_json = _dumps(payload.units)

        if payload.mass is not None:
            version.mass_json = _dumps(payload.mass)

        if payload.family_table is not None:
            version.family_table_json = _dumps(payload.family_table)

        if payload.features is not None:
            version.features_json = _dumps(normalize_feature_rows(payload.features))

        if bom_payload is not None:
            version.bom_json = _dumps(bom_payload)

        if is_snapshot or bool(payload.parameters):
            self._write_parameters(session, obj, version, payload.parameters)

        if is_snapshot or bool(payload.dependencies) or bom_payload is not None:
            self._write_dependencies(session, obj, payload.dependencies, bom_payload)
            # Assembly GetSkeleton → SKELETON edges: set those part children's role now
            # so Type updates without relying on a later part Collect seeing GetSkeleton.
            self._flag_skeleton_children_from_new_edges(
                session, obj, payload.dependencies, bom_payload, stored_identity
            )
        elif stored_identity and stored_identity.get("skeleton_filename"):
            self._flag_skeleton_children_from_new_edges(
                session, obj, None, None, stored_identity
            )

        # Part Collect: if a parent already stored a SKELETON edge to this part, win.
        self._apply_skeleton_role_from_parent_edges(session, obj, version)

        session.flush()
        return self.get(session, object_uuid, version.uuid)

    def get(
        self,
        session: Session,
        object_uuid: str,
        version_uuid: str | None = None,
    ) -> CreoMetadataResponse:
        obj = self._objects.get_object(session, object_uuid)
        version = self._resolve_version(session, obj, version_uuid)
        if version is None:
            return CreoMetadataResponse(object_id=obj.uuid, captured=False)

        params = session.scalars(
            select(Parameter)
            .where(Parameter.version_id == version.id)
            .order_by(Parameter.name.asc())
        ).all()
        deps = session.scalars(
            select(Dependency).where(Dependency.parent_object_id == obj.id)
        ).all()
        child_ids = [edge.child_object_id for edge in deps]
        children = {
            row.id: row
            for row in session.scalars(
                select(EngineeringObject).where(EngineeringObject.id.in_(child_ids))
            ).all()
        } if child_ids else {}

        dep_payloads: list[CreoDependencyPayload] = []
        for edge in deps:
            child = children.get(edge.child_object_id)
            if child is None:
                continue
            dep_payloads.append(
                CreoDependencyPayload(
                    filename=child.filename,
                    quantity=float(edge.quantity or 1.0),
                    dependency_type=edge.dependency_type or DependencyType.ASSEMBLY_MEMBER.value,
                )
            )

        identity = _loads(version.identity_json)
        if isinstance(identity, dict):
            normalize_creo_identity(identity)
        materials = _loads(version.materials_json)
        bom = _loads(version.bom_json)
        units = _loads(version.units_json)
        mass = _loads(version.mass_json)
        family_table = _loads(version.family_table_json)
        features_raw = _loads(version.features_json)
        features = (
            normalize_feature_rows(features_raw) if isinstance(features_raw, list) else None
        )
        captured = bool(
            identity
            or materials
            or bom
            or units
            or mass
            or family_table
            or features
            or params
            or dep_payloads
        )
        return CreoMetadataResponse(
            object_id=obj.uuid,
            version_id=version.uuid,
            identity=identity if isinstance(identity, dict) else None,
            parameters=[
                CreoParamPayload(
                    name=row.name,
                    value=row.value,
                    data_type=row.data_type or "STRING",
                    units=row.units,
                    description=row.description,
                    is_designated=bool(row.is_designated),
                )
                for row in params
            ],
            materials=materials if isinstance(materials, dict) else None,
            dependencies=dep_payloads,
            bom=bom,
            units=units if isinstance(units, dict) else None,
            mass=mass if isinstance(mass, dict) else None,
            family_table=family_table if isinstance(family_table, dict) else None,
            features=features,
            captured=captured,
        )

    def where_used_index_present(self, session: Session, product_id: int) -> bool:
        """True when at least one Dependency row exists for the product."""
        return (
            session.scalar(
                select(Dependency.id).where(Dependency.product_id == product_id).limit(1)
            )
            is not None
        )

    def upsert_dependency_edges(
        self,
        session: Session,
        product_id: int,
        edges: list[tuple[int, int, str]],
    ) -> tuple[int, int]:
        """Insert missing Dependency rows. Returns (added, already_existing)."""
        added = 0
        existing = 0
        for parent_id, child_id, dep_type in edges:
            if parent_id == child_id:
                continue
            found = session.scalar(
                select(Dependency).where(
                    Dependency.product_id == product_id,
                    Dependency.parent_object_id == parent_id,
                    Dependency.child_object_id == child_id,
                    Dependency.dependency_type == dep_type,
                )
            )
            if found is not None:
                existing += 1
                continue
            session.add(
                Dependency(
                    product_id=product_id,
                    parent_object_id=parent_id,
                    child_object_id=child_id,
                    dependency_type=dep_type,
                    quantity=1.0,
                )
            )
            added += 1
        if added:
            session.flush()
        return added, existing

    def prune_assembly_name_magnets(
        self,
        session: Session,
        product_id: int,
        *,
        max_parents: int = _MAX_WHERE_USED_ASM_PARENTS,
    ) -> int:
        """Drop assembly membership edges into name-table magnets.

        Creo tips often mention the project root (e.g. ``844j``) in hundreds of
        files. Those stem hits create hundreds of false parents and hide the
        true Top Level root. Assemblies with more than ``max_parents`` distinct
        ASSEMBLY_MEMBER parents are treated as magnets: all such incoming edges
        are removed so the root can surface, while real sub-asms (few parents)
        keep their links.
        """
        from sqlalchemy import func

        Child = aliased(EngineeringObject)
        crowded = (
            select(Dependency.child_object_id)
            .join(Child, Child.id == Dependency.child_object_id)
            .where(
                Dependency.product_id == product_id,
                Dependency.dependency_type == DependencyType.ASSEMBLY_MEMBER.value,
                Child.object_type == _ASSEMBLY_TYPE,
            )
            .group_by(Dependency.child_object_id)
            .having(func.count(Dependency.parent_object_id) > int(max_parents))
        )
        result = session.execute(
            delete(Dependency).where(
                Dependency.product_id == product_id,
                Dependency.dependency_type == DependencyType.ASSEMBLY_MEMBER.value,
                Dependency.child_object_id.in_(crowded),
            )
        )
        removed = int(result.rowcount or 0)
        if removed:
            session.flush()
            logger.info(
                "Where Used pruned %s magnet edges (asm parents > %s) for product %s",
                removed,
                max_parents,
                product_id,
            )
        return removed

    def top_level_assembly_uuids(self, session: Session, product_id: int) -> list[str]:
        """Assemblies not used by another assembly (drawing parents ignored).

        Requires a Where Used index. An assembly referenced only from a drawing
        still counts as top-level. Default Creo datum-named assemblies
        (``front.asm``, ``left.asm``, …) are omitted from the pill — not
        common roots like ``top.asm``.
        """
        Parent = aliased(EngineeringObject)
        referenced = (
            select(Dependency.child_object_id)
            .join(Parent, Parent.id == Dependency.parent_object_id)
            .where(
                Dependency.product_id == product_id,
                Parent.object_type != _DRAWING_PARENT,
                Dependency.dependency_type != DependencyType.DRAWING_MODEL.value,
            )
        )
        rows = session.scalars(
            select(EngineeringObject)
            .where(
                EngineeringObject.product_id == product_id,
                EngineeringObject.object_type == _ASSEMBLY_TYPE,
                ~EngineeringObject.id.in_(referenced),
            )
            .order_by(EngineeringObject.filename)
        ).all()
        out: list[str] = []
        for row in rows:
            stem = Path(
                CreoFileManager.normalize_creo_filename(row.filename)
            ).stem.lower()
            if stem in _TOP_LEVEL_STEM_OMIT:
                continue
            out.append(str(row.uuid))
        return out

    def where_used(
        self,
        session: Session,
        object_uuid: str,
        *,
        debug: bool = False,
        vault_scan: bool = True,
    ) -> WhereUsedResponse:
        """Parents that reference this object.

        Order of operations often leaves Dependency empty: assembly metadata is
        captured before children exist in the product, so edges never get written.
        We still answer from (1) Dependency rows, (2) stored BOM JSON on siblings,
        (3) optional vault file bytes for asm/drw that embed this name.

        ``vault_scan=False`` skips (3) — use on HTML page render so History/detail
        stay fast on multi-thousand-file products (Where Used tab loads via API).
        """
        obj = self._objects.get_object(session, object_uuid)
        edges = session.scalars(
            select(Dependency).where(Dependency.child_object_id == obj.id)
        ).all()
        parent_ids = [edge.parent_object_id for edge in edges]
        parents = {
            row.id: row
            for row in session.scalars(
                select(EngineeringObject).where(EngineeringObject.id.in_(parent_ids))
            ).all()
        } if parent_ids else {}

        items_by_parent: dict[str, WhereUsedItem] = {}
        for edge in edges:
            parent = parents.get(edge.parent_object_id)
            if parent is None:
                continue
            items_by_parent[parent.uuid] = WhereUsedItem(
                object_id=parent.uuid,
                filename=parent.filename,
                relative_path=parent.relative_path,
                display_revision=f"{parent.revision}.{parent.iteration}",
                quantity=float(edge.quantity or 1.0),
                dependency_type=edge.dependency_type or DependencyType.ASSEMBLY_MEMBER.value,
                object_type=parent.object_type,
                type_label=display_type_label(parent.filename, parent.object_type),
            )

        siblings = self._objects.list_objects(session, obj.product_id)
        target_keys = set(bom_where_used_keys(obj.filename))
        debug_bom_hits: list[str] = []
        debug_vault: list[dict[str, object]] = []

        # Stored BOM trees — covers captures that never wrote Dependency rows
        # (e.g. nested BOM skipped, or assembly captured before children existed).
        if target_keys:
            for other in siblings:
                if other.id == obj.id or other.uuid in items_by_parent:
                    continue
                version = self._resolve_version(session, other, None)
                if version is None:
                    continue
                bom = _loads(version.bom_json)
                if not bom:
                    continue
                matched_qty = 0.0
                matched_type = DependencyType.ASSEMBLY_MEMBER.value
                for filename, qty, dep_type in self._flatten_bom(bom):
                    if self._skip_dependency_ref(dep_type, filename, other.filename):
                        continue
                    if set(bom_where_used_keys(filename)) & target_keys:
                        matched_qty += float(qty or 1.0)
                        matched_type = dep_type
                if matched_qty <= 0:
                    continue
                if debug:
                    debug_bom_hits.append(other.filename)
                items_by_parent[other.uuid] = WhereUsedItem(
                    object_id=other.uuid,
                    filename=other.filename,
                    relative_path=other.relative_path,
                    display_revision=f"{other.revision}.{other.iteration}",
                    quantity=matched_qty,
                    dependency_type=matched_type,
                    object_type=other.object_type,
                    type_label=display_type_label(other.filename, other.object_type),
                )

        # Vault byte scan: works even when Creo.JS never captured a BOM (add-only
        # order of operations, or metadata gather failed on the parent).
        # Skip automatically on huge products — reading every asm/drw hangs the server.
        _VAULT_SCAN_ASM_CAP = 80
        asm_candidates = [
            other
            for other in siblings
            if other.id != obj.id
            and other.uuid not in items_by_parent
            and needs_open_dependencies(other.object_type, other.filename)
        ]
        vault_scan_skipped = False
        if vault_scan and len(asm_candidates) > _VAULT_SCAN_ASM_CAP:
            vault_scan_skipped = True
            vault_scan = False
            logger.info(
                "Where-used vault scan skipped for %s (%s asm/drw candidates > %s)",
                obj.filename,
                len(asm_candidates),
                _VAULT_SCAN_ASM_CAP,
            )
        if vault_scan and self._workspaces is not None:
            product = session.get(Product, obj.product_id)
            if product is not None:
                for other in asm_candidates:
                    entry: dict[str, object] | None = (
                        {
                            "filename": other.filename,
                            "object_type": other.object_type,
                        }
                        if debug
                        else None
                    )
                    try:
                        path = self._workspaces.locate_content(product, other)
                    except PathValidationError as exc:
                        if entry is not None:
                            entry["locate"] = "missing"
                            entry["error"] = str(exc)
                            debug_vault.append(entry)
                        continue
                    except Exception as exc:
                        logger.debug(
                            "Where-used vault locate failed for %s",
                            other.filename,
                            exc_info=True,
                        )
                        if entry is not None:
                            entry["locate"] = "error"
                            entry["error"] = str(exc)
                            debug_vault.append(entry)
                        continue
                    matched = model_references_filename(path, obj.filename)
                    if entry is not None:
                        entry["locate"] = "ok"
                        entry["path"] = str(path)
                        try:
                            entry["size"] = int(path.stat().st_size)
                        except OSError:
                            entry["size"] = -1
                        entry["matched"] = matched
                        debug_vault.append(entry)
                    if not matched:
                        continue
                    items_by_parent[other.uuid] = WhereUsedItem(
                        object_id=other.uuid,
                        filename=other.filename,
                        relative_path=other.relative_path,
                        display_revision=f"{other.revision}.{other.iteration}",
                        quantity=1.0,
                        dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
                        object_type=other.object_type,
                        type_label=display_type_label(other.filename, other.object_type),
                    )

        items = sorted(items_by_parent.values(), key=lambda row: row.filename.lower())
        payload = WhereUsedResponse(object_id=obj.uuid, items=items)
        if debug:
            asm_drw = [row.filename for row in asm_candidates]
            payload.debug = {
                "workspaces_wired": self._workspaces is not None,
                "sibling_count": len(siblings),
                "dependency_edge_count": len(edges),
                "target_keys": sorted(target_keys),
                "asm_drw_candidates": asm_drw,
                "bom_hits": debug_bom_hits,
                "vault_scan": debug_vault,
                "vault_scan_enabled": vault_scan and not vault_scan_skipped,
                "vault_scan_skipped": vault_scan_skipped,
            }
        return payload

    def rebuild_where_used_from_vault(
        self,
        session: Session,
        product_uuid: str,
        *,
        offset: int = 0,
        limit: int = 8,
    ) -> RebuildWhereUsedResponse:
        """Scan vault asm/drw bytes and rewrite Dependency rows (chunked).

        At offset 0, clears existing ASSEMBLY_MEMBER / DRAWING_MODEL edges so
        stale false parents (glued substrings / removed components) cannot stick.
        Then indexes bounded ``name.ext`` and unique bare Creo component names
        from vault bytes. After this, Where Used is a SQL lookup on ``dependencies``.
        """
        if self._workspaces is None:
            raise ValidationAppError(
                "Vault indexing is not available (workspace service not configured)."
            )
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None:
            raise ObjectNotFoundError(
                "Product not found.",
                details={"product_id": product_uuid},
            )
        # Full rebuild: vault scan is source of truth for asm/drw membership.
        # Upsert-only left false Top Level / Where Used parents forever.
        start = max(0, int(offset))
        if start == 0:
            session.execute(
                delete(Dependency).where(
                    Dependency.product_id == product.id,
                    Dependency.dependency_type.in_(
                        (
                            DependencyType.ASSEMBLY_MEMBER.value,
                            DependencyType.DRAWING_MODEL.value,
                        )
                    ),
                )
            )
            session.flush()
            logger.info(
                "Cleared ASSEMBLY_MEMBER/DRAWING_MODEL edges before Where Used rebuild (%s)",
                product_uuid,
            )
        objects = self._objects.list_objects(session, product.id)
        parents = sorted(
            [row for row in objects if needs_open_dependencies(row.object_type, row.filename)],
            key=lambda row: (row.filename or "").lower(),
        )
        total = len(parents)
        take = max(1, min(int(limit), 40))
        chunk = parents[start : start + take]
        if not chunk:
            return RebuildWhereUsedResponse(
                parents_total=total,
                parents_processed=0,
                next_offset=start,
                done=True,
            )

        # Map logical name.ext → object; unique stems → object (Creo often omits .prt).
        by_key: dict[str, EngineeringObject] = {}
        stem_to_rows: dict[str, list[EngineeringObject]] = {}
        candidate_names: list[str] = []
        for row in objects:
            candidate_names.append(row.filename)
            logical = CreoFileManager.normalize_creo_filename(row.filename).lower()
            if not logical or "." not in logical:
                continue
            by_key.setdefault(logical, row)
            stem = Path(logical).stem.lower()
            if len(stem) >= 4:
                stem_to_rows.setdefault(stem, []).append(row)

        # Creo component tables use bare names; require token boundaries so glued
        # substrings (false Top Level parents) still do not match. Assemblies
        # claimed by dozens/hundreds of parents are pruned after the full scan
        # (name-table magnets such as the project root).
        matcher = CadNameMatcher(
            candidate_names,
            include_stems=True,
            require_boundaries=True,
            min_stem_len=4,
            unique_stems_only=True,
            blocked_stems=_WHERE_USED_STEM_BLOCKLIST,
        )
        edges_added = 0
        edges_existing = 0
        missing = 0
        scanned: list[str] = []
        # Collect links while reading vault bytes — do not write until the scan
        # for this chunk finishes, or SQLite holds a write lock across multi‑MB reads
        # and hangs the rest of CreoPDM (status GET, UI, etc.).
        pending: list[tuple[int, int, str]] = []
        # End the list_objects read transaction before vault I/O.
        session.commit()

        for parent in chunk:
            scanned.append(parent.filename)
            try:
                path = self._workspaces.locate_content(product, parent)
            except PathValidationError:
                missing += 1
                continue
            except Exception:
                logger.debug(
                    "Rebuild where-used locate failed for %s",
                    parent.filename,
                    exc_info=True,
                )
                missing += 1
                continue
            # Full tip — component tables are often past the 8 MiB Open window.
            blob = read_model_scan_blob(path, max_bytes=_WHERE_USED_SCAN_LIMIT)
            found = matcher.find(blob) if blob else set()
            child_ids: set[int] = set()
            for name in found:
                logical = CreoFileManager.normalize_creo_filename(name).lower()
                if not logical:
                    continue
                child = by_key.get(logical)
                if child is None and "." not in logical and len(logical) >= 4:
                    rows = stem_to_rows.get(logical) or []
                    if len(rows) == 1:
                        child = rows[0]
                    else:
                        asms = [
                            row
                            for row in rows
                            if Path(
                                CreoFileManager.normalize_creo_filename(row.filename)
                            ).suffix.lower()
                            == ".asm"
                        ]
                        if len(asms) == 1:
                            child = asms[0]
                if child is None or child.id == parent.id:
                    continue
                child_ids.add(child.id)

            dep_type = (
                DependencyType.DRAWING_MODEL.value
                if Path(
                    CreoFileManager.normalize_creo_filename(parent.filename)
                ).suffix.lower()
                == ".drw"
                else DependencyType.ASSEMBLY_MEMBER.value
            )
            for child_id in child_ids:
                pending.append((parent.id, child_id, dep_type))

        edges_added, edges_existing = self.upsert_dependency_edges(
            session, product.id, pending
        )

        next_offset = start + len(chunk)
        done = next_offset >= total
        if done:
            # Strip false parents of project-root magnets after the full graph exists.
            self.prune_assembly_name_magnets(session, product.id)
        return RebuildWhereUsedResponse(
            parents_total=total,
            parents_processed=len(chunk),
            next_offset=next_offset,
            done=done,
            edges_added=edges_added,
            edges_existing=edges_existing,
            parents_missing_vault=missing,
            parents_scanned=scanned,
        )

    def _resolve_version(
        self,
        session: Session,
        obj: EngineeringObject,
        version_uuid: str | None,
    ) -> ObjectVersion | None:
        if version_uuid:
            version = session.scalar(
                select(ObjectVersion).where(
                    ObjectVersion.uuid == version_uuid,
                    ObjectVersion.object_id == obj.id,
                )
            )
            if version is None:
                raise ObjectNotFoundError(
                    "Version not found for this object.",
                    details={"version_id": version_uuid, "object_id": obj.uuid},
                )
            return version
        return obj.current_version

    def clear_product_metadata(self, session: Session, product: Product) -> dict[str, int]:
        """Wipe stored Creo metadata for every object in the product (Collect start)."""
        ensure_product_mutable(product, action="update metadata")
        objects = self._objects.list_objects(session, product.id)
        object_ids = [row.id for row in objects]
        params_deleted = 0
        versions_cleared = 0
        if object_ids:
            params_deleted = int(
                session.execute(delete(Parameter).where(Parameter.object_id.in_(object_ids))).rowcount
                or 0
            )
            result = session.execute(
                update(ObjectVersion)
                .where(ObjectVersion.object_id.in_(object_ids))
                .values(
                    identity_json=None,
                    materials_json=None,
                    bom_json=None,
                    units_json=None,
                    mass_json=None,
                    family_table_json=None,
                    features_json=None,
                )
            )
            versions_cleared = int(result.rowcount or 0)
        deps_deleted = int(
            session.execute(delete(Dependency).where(Dependency.product_id == product.id)).rowcount
            or 0
        )
        session.flush()
        return {
            "objects": len(object_ids),
            "versions_cleared": versions_cleared,
            "parameters_deleted": params_deleted,
            "dependencies_deleted": deps_deleted,
        }

    def _keep_part_skeleton_role(
        self,
        obj: EngineeringObject,
        previous: Any,
        identity: dict[str, Any],
    ) -> bool:
        logical = CreoFileManager.logical_filename(obj.filename or "").lower()
        if not logical.endswith(".prt"):
            return False
        prev_role = ""
        if isinstance(previous, dict):
            prev = dict(previous)
            normalize_creo_identity(prev)
            prev_role = str(prev.get("model_role") or "").upper()
        new_role = str(identity.get("model_role") or "").upper()
        return prev_role == DependencyType.SKELETON.value and new_role != DependencyType.SKELETON.value

    def flag_skeleton_parts_by_filenames(
        self,
        session: Session,
        product: Product,
        filenames: list[str],
    ) -> dict[str, int]:
        """Set model_role=SKELETON on matching .prt tips (Collect end-of-session pass)."""
        ensure_product_mutable(product)
        skel_keys: set[str] = set()
        for name in filenames or []:
            text = str(name or "").strip()
            if text:
                skel_keys.update(bom_lookup_keys(text))
        if not skel_keys:
            return {"requested": 0, "flagged": 0}
        flagged = 0
        for row in self._objects.list_objects(session, product.id):
            if not (set(bom_lookup_keys(row.filename)) & skel_keys):
                continue
            before = ""
            ver = self._resolve_version(session, row, None)
            if ver is not None:
                prev = _loads(ver.identity_json)
                if isinstance(prev, dict):
                    before = str(prev.get("model_role") or "").upper()
            self._set_part_skeleton_role(session, row)
            ver = self._resolve_version(session, row, None)
            role = ""
            if ver is not None:
                data = _loads(ver.identity_json)
                if isinstance(data, dict):
                    role = str(data.get("model_role") or "").upper()
            if role == DependencyType.SKELETON.value:
                flagged += 1
                if before != role:
                    logger.info(
                        "Flagged skeleton part %s (was role=%s)",
                        row.filename,
                        before or "-",
                    )
        session.flush()
        return {"requested": len(skel_keys), "flagged": flagged}

    def _set_part_skeleton_role(
        self,
        session: Session,
        child: EngineeringObject,
    ) -> None:
        logical = CreoFileManager.logical_filename(child.filename or "").lower()
        if not logical.endswith(".prt"):
            return
        child_version = self._resolve_version(session, child, None)
        if child_version is None:
            return
        identity = _loads(child_version.identity_json)
        if not isinstance(identity, dict):
            identity = {}
        else:
            identity = dict(identity)
        normalize_creo_identity(identity)
        kind = str(identity.get("model_type") or "")
        if kind and kind != "PART":
            return
        if str(identity.get("model_role") or "").upper() == DependencyType.SKELETON.value:
            return
        identity["model_type"] = "PART"
        identity["model_role"] = DependencyType.SKELETON.value
        if not identity.get("file_name"):
            identity["file_name"] = child.filename
        normalize_creo_identity(identity)
        child_version.identity_json = _dumps(identity)

    def _flag_skeleton_children_from_new_edges(
        self,
        session: Session,
        parent: EngineeringObject,
        dependencies: list[CreoDependencyPayload] | None,
        bom_payload: Any,
        identity: dict[str, Any] | None = None,
    ) -> None:
        """When this assembly reports a skeleton part, mark matching .prt children."""
        skel_keys: set[str] = set()
        for item in dependencies or []:
            if str(getattr(item, "dependency_type", "") or "").upper() != DependencyType.SKELETON.value:
                continue
            name = str(getattr(item, "filename", "") or "").strip()
            if name:
                skel_keys.update(bom_lookup_keys(name))
        if bom_payload is not None:
            for filename, _qty, dep_type in self._flatten_bom(bom_payload):
                if str(dep_type or "").upper() != DependencyType.SKELETON.value:
                    continue
                skel_keys.update(bom_lookup_keys(filename))
        skel_name = ""
        if isinstance(identity, dict):
            skel_name = str(identity.get("skeleton_filename") or "").strip()
        if skel_name:
            skel_keys.update(bom_lookup_keys(skel_name))
        if not skel_keys:
            return
        for row in self._objects.list_objects(session, parent.product_id):
            if row.id == parent.id:
                continue
            if not (set(bom_lookup_keys(row.filename)) & skel_keys):
                continue
            self._set_part_skeleton_role(session, row)

    def _apply_skeleton_role_from_parent_edges(
        self,
        session: Session,
        obj: EngineeringObject,
        version: ObjectVersion,
    ) -> None:
        logical = CreoFileManager.logical_filename(obj.filename or "").lower()
        if not logical.endswith(".prt"):
            return
        has_edge = session.scalar(
            select(Dependency.id)
            .where(
                Dependency.child_object_id == obj.id,
                Dependency.dependency_type == DependencyType.SKELETON.value,
            )
            .limit(1)
        )
        if has_edge is None:
            # GetSkeleton often lands only on the parent identity stem (no SKELETON edge).
            child_keys = set(bom_lookup_keys(obj.filename))
            matched = False
            for row in self._objects.list_objects(session, obj.product_id):
                if row.id == obj.id:
                    continue
                ver = getattr(row, "current_version", None)
                raw = getattr(ver, "identity_json", None) if ver is not None else None
                data = _loads(raw)
                if not isinstance(data, dict):
                    continue
                skel_name = str(data.get("skeleton_filename") or "").strip()
                if skel_name and (set(bom_lookup_keys(skel_name)) & child_keys):
                    matched = True
                    break
            if not matched:
                return
        identity = _loads(version.identity_json)
        if not isinstance(identity, dict):
            identity = {}
        else:
            identity = dict(identity)
        normalize_creo_identity(identity)
        kind = str(identity.get("model_type") or "")
        if kind and kind != "PART":
            return
        identity["model_type"] = "PART"
        identity["model_role"] = DependencyType.SKELETON.value
        if not identity.get("file_name"):
            identity["file_name"] = obj.filename
        normalize_creo_identity(identity)
        version.identity_json = _dumps(identity)

    def _erase_object_metadata_tables(
        self,
        session: Session,
        obj: EngineeringObject,
        version: ObjectVersion,
        *,
        clear_parameters: bool,
        clear_dependencies: bool,
    ) -> None:
        """Delete this object's Parameter / Dependency rows before rewrite."""
        if clear_parameters:
            session.execute(delete(Parameter).where(Parameter.version_id == version.id))
        if clear_dependencies:
            session.execute(delete(Dependency).where(Dependency.parent_object_id == obj.id))

    def _write_parameters(
        self,
        session: Session,
        obj: EngineeringObject,
        version: ObjectVersion,
        parameters: list[CreoParamPayload],
    ) -> None:
        for item in parameters:
            name = (item.name or "").strip()
            if not name:
                continue
            session.add(
                Parameter(
                    object_id=obj.id,
                    version_id=version.id,
                    name=name[:128],
                    value=item.value,
                    data_type=(item.data_type or "STRING")[:32],
                    units=(item.units or None),
                    description=item.description,
                    is_designated=bool(item.is_designated),
                )
            )

    def _write_dependencies(
        self,
        session: Session,
        parent: EngineeringObject,
        dependencies: list[CreoDependencyPayload],
        bom: Any,
    ) -> None:
        refs: list[tuple[str, str, float]] = []
        bom_refs = list(self._flatten_bom(bom)) if bom is not None else []
        bom_has_members = any(
            not self._skip_dependency_ref(dep_type, filename, parent.filename)
            for filename, _qty, dep_type in bom_refs
        )
        if bom_has_members:
            for filename, qty, dep_type in bom_refs:
                refs.append((filename, dep_type, float(qty or 1.0)))
            covered: set[str] = set()
            for filename, _dep_type, _qty in refs:
                if self._skip_dependency_ref(_dep_type, filename, parent.filename):
                    continue
                covered.update(bom_lookup_keys(filename))
            for item in dependencies:
                key_name = (item.filename or "").strip()
                if not key_name:
                    continue
                dep_type = (item.dependency_type or DependencyType.ASSEMBLY_MEMBER.value).strip()
                if self._skip_dependency_ref(dep_type, key_name, parent.filename):
                    continue
                # Skip assembly members already in the BOM, but keep SKELETON so
                # GetSkeleton can upgrade ASSEMBLY_MEMBER → SKELETON on merge.
                if set(bom_lookup_keys(key_name)) & covered:
                    if dep_type.upper() != DependencyType.SKELETON.value:
                        continue
                    refs.append((key_name, dep_type, 0.0))  # type upgrade only
                    continue
                refs.append((key_name, dep_type, float(item.quantity or 1.0)))
        else:
            for item in dependencies:
                key_name = (item.filename or "").strip()
                if not key_name:
                    continue
                dep_type = (item.dependency_type or DependencyType.ASSEMBLY_MEMBER.value).strip()
                refs.append((key_name, dep_type, float(item.quantity or 1.0)))

        if not refs:
            return

        siblings = self._objects.list_objects(session, parent.product_id)
        by_key: dict[str, EngineeringObject] = {}
        for row in siblings:
            if row.id == parent.id:
                continue
            for key in bom_lookup_keys(row.filename):
                by_key.setdefault(key, row)

        # child_id → (dep_type, quantity). Prefer SKELETON over ASSEMBLY_MEMBER when
        # GetSkeleton and BOM both mention the same component.
        by_child: dict[int, tuple[str, float]] = {}
        for filename, dep_type, quantity in refs:
            if self._skip_dependency_ref(dep_type, filename, parent.filename):
                continue
            child = None
            for key in bom_lookup_keys(filename):
                child = by_key.get(key)
                if child is not None:
                    break
            if child is None:
                continue
            kind = (dep_type or DependencyType.ASSEMBLY_MEMBER.value)[:32]
            qty = float(quantity or 1.0)
            prev = by_child.get(child.id)
            if prev is None:
                by_child[child.id] = (kind, qty)
                continue
            prev_kind, prev_qty = prev
            merged_qty = prev_qty + qty
            if prev_kind.upper() == DependencyType.SKELETON.value or kind.upper() == DependencyType.SKELETON.value:
                by_child[child.id] = (DependencyType.SKELETON.value, merged_qty)
            else:
                by_child[child.id] = (prev_kind, merged_qty)

        for child_id, (dep_type, quantity) in by_child.items():
            session.add(
                Dependency(
                    product_id=parent.product_id,
                    parent_object_id=parent.id,
                    child_object_id=child_id,
                    dependency_type=dep_type,
                    quantity=quantity,
                )
            )

    @staticmethod
    def _skip_dependency_ref(dep_type: str, filename: str, parent_filename: str) -> bool:
        kind = (dep_type or "").strip().upper()
        if kind in {"ASSEMBLY_ROOT", "ROOT"}:
            return True
        parent_keys = set(bom_lookup_keys(parent_filename))
        child_keys = set(bom_lookup_keys(filename))
        return bool(parent_keys and child_keys and (parent_keys & child_keys))

    def _flatten_bom(self, bom: Any) -> list[tuple[str, float, str]]:
        rows: list[tuple[str, float, str]] = []

        def as_dict(node: Any) -> dict[str, Any] | None:
            if isinstance(node, dict):
                return node
            if hasattr(node, "model_dump"):
                dumped = node.model_dump()
                return dumped if isinstance(dumped, dict) else None
            return None

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            data = as_dict(node)
            if data is None:
                return
            filename = str(data.get("filename") or "").strip()
            dep_type = str(data.get("dependency_type") or DependencyType.ASSEMBLY_MEMBER.value)
            qty = float(data.get("quantity") or 1.0)
            if filename:
                rows.append((filename, qty, dep_type))
            children = data.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)

        walk(bom)
        return rows