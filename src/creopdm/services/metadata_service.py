"""Persist Creo.JS identity, parameters, materials, BOM, and dependency graph."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from creopdm.constants import DependencyType
from creopdm.exceptions import ObjectNotFoundError, ValidationAppError
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.version import ObjectVersion
from creopdm.schemas.common import (
    CreoDependencyPayload,
    CreoMetadataRequest,
    CreoMetadataResponse,
    CreoParamPayload,
    WhereUsedItem,
    WhereUsedResponse,
)
from creopdm.services.object_service import ObjectService
from creopdm.utils.bom_match import bom_lookup_keys, bom_where_used_keys
from creopdm.utils.classify import display_type_label

logger = logging.getLogger(__name__)


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
    def __init__(self, objects: ObjectService) -> None:
        self._objects = objects

    def save(
        self,
        session: Session,
        object_uuid: str,
        payload: CreoMetadataRequest,
    ) -> CreoMetadataResponse:
        obj = self._objects.get_object(session, object_uuid)
        version = self._resolve_version(session, obj, payload.version_id)
        if version is None:
            raise ValidationAppError(
                "This file has no version to attach Creo metadata to.",
                details={"object_id": object_uuid},
            )

        if payload.identity is not None:
            version.identity_json = _dumps(payload.identity)
            common = str(payload.identity.get("common_name") or "").strip()
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
            version.features_json = _dumps(payload.features)

        bom_payload = payload.bom
        if bom_payload is not None:
            if hasattr(bom_payload, "model_dump"):
                bom_payload = bom_payload.model_dump()
            elif isinstance(bom_payload, list):
                bom_payload = [
                    item.model_dump() if hasattr(item, "model_dump") else item for item in bom_payload
                ]
            version.bom_json = _dumps(bom_payload)

        self._replace_parameters(session, obj, version, payload.parameters)

        if payload.dependencies or bom_payload is not None:
            self._replace_dependencies(session, obj, payload.dependencies, bom_payload)

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
        materials = _loads(version.materials_json)
        bom = _loads(version.bom_json)
        units = _loads(version.units_json)
        mass = _loads(version.mass_json)
        family_table = _loads(version.family_table_json)
        features_raw = _loads(version.features_json)
        features = features_raw if isinstance(features_raw, list) else None
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

    def where_used(self, session: Session, object_uuid: str) -> WhereUsedResponse:
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

        # Also scan stored BOM trees — older captures may not have written Dependency rows
        # (nested BOM was skipped when ListDependencies returned anything).
        target_keys = set(bom_where_used_keys(obj.filename))
        if target_keys:
            siblings = self._objects.list_objects(session, obj.project_id)
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

        items = sorted(items_by_parent.values(), key=lambda row: row.filename.lower())
        return WhereUsedResponse(object_id=obj.uuid, items=items)

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

    def _replace_parameters(
        self,
        session: Session,
        obj: EngineeringObject,
        version: ObjectVersion,
        parameters: list[CreoParamPayload],
    ) -> None:
        session.execute(delete(Parameter).where(Parameter.version_id == version.id))
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

    def _replace_dependencies(
        self,
        session: Session,
        parent: EngineeringObject,
        dependencies: list[CreoDependencyPayload],
        bom: Any,
    ) -> None:
        session.execute(delete(Dependency).where(Dependency.parent_object_id == parent.id))

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
                # Skip assembly members already represented in the BOM tree.
                if set(bom_lookup_keys(key_name)) & covered:
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

        siblings = self._objects.list_objects(session, parent.project_id)
        by_key: dict[str, EngineeringObject] = {}
        for row in siblings:
            if row.id == parent.id:
                continue
            for key in bom_lookup_keys(row.filename):
                by_key.setdefault(key, row)

        by_child: dict[tuple[int, str], float] = {}
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
            edge_key = (child.id, (dep_type or DependencyType.ASSEMBLY_MEMBER.value)[:32])
            by_child[edge_key] = by_child.get(edge_key, 0.0) + float(quantity or 1.0)

        for (child_id, dep_type), quantity in by_child.items():
            session.add(
                Dependency(
                    project_id=parent.project_id,
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