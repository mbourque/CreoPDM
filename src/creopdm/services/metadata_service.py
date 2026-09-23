"""Persist Creo.JS identity, parameters, materials, BOM, and dependency graph."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from creopdm.constants import DependencyType
from creopdm.creo.file_manager import CreoFileManager
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


def _logical_key(filename: str) -> str:
    return CreoFileManager.logical_filename(filename).lower()


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

        if payload.dependencies or payload.bom is not None:
            self._replace_dependencies(session, obj, payload.dependencies, payload.bom)

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
        captured = bool(
            identity or materials or bom or params or dep_payloads
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

        items: list[WhereUsedItem] = []
        for edge in edges:
            parent = parents.get(edge.parent_object_id)
            if parent is None:
                continue
            items.append(
                WhereUsedItem(
                    object_id=parent.uuid,
                    filename=parent.filename,
                    relative_path=parent.relative_path,
                    display_revision=f"{parent.revision}.{parent.iteration}",
                    quantity=float(edge.quantity or 1.0),
                    dependency_type=edge.dependency_type or DependencyType.ASSEMBLY_MEMBER.value,
                    object_type=parent.object_type,
                    type_label=display_type_label(parent.filename, parent.object_type),
                )
            )
        items.sort(key=lambda row: row.filename.lower())
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

        aggregated: dict[tuple[str, str], float] = {}
        for item in dependencies:
            key_name = (item.filename or "").strip()
            if not key_name:
                continue
            dep_type = (item.dependency_type or DependencyType.ASSEMBLY_MEMBER.value).strip()
            qty = float(item.quantity or 1.0)
            key = (_logical_key(key_name), dep_type)
            aggregated[key] = aggregated.get(key, 0.0) + qty

        if not aggregated and bom is not None:
            for filename, qty, dep_type in self._flatten_bom(bom):
                key = (_logical_key(filename), dep_type)
                aggregated[key] = aggregated.get(key, 0.0) + qty

        if not aggregated:
            return

        siblings = self._objects.list_objects(session, parent.project_id)
        by_logical = {_logical_key(row.filename): row for row in siblings if row.id != parent.id}

        for (logical, dep_type), quantity in aggregated.items():
            child = by_logical.get(logical)
            if child is None:
                continue
            session.add(
                Dependency(
                    project_id=parent.project_id,
                    parent_object_id=parent.id,
                    child_object_id=child.id,
                    dependency_type=dep_type[:32],
                    quantity=quantity,
                )
            )

    def _flatten_bom(self, bom: Any) -> list[tuple[str, float, str]]:
        rows: list[tuple[str, float, str]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, dict):
                return
            filename = str(node.get("filename") or "").strip()
            dep_type = str(node.get("dependency_type") or DependencyType.ASSEMBLY_MEMBER.value)
            qty = float(node.get("quantity") or 1.0)
            if filename:
                rows.append((filename, qty, dep_type))
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)

        walk(bom)
        return rows
