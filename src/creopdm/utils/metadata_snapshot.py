"""The Creo metadata of file versions, as one JSON document per version.

A baseline copies it for every member when it is made, so what the baseline shows can never change
afterwards, even if the version's own metadata is collected again.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from creopdm.models.parameter import Parameter
from creopdm.models.version import ObjectVersion

_FIELDS = (
    ("identity", "identity_json"),
    ("materials", "materials_json"),
    ("units", "units_json"),
    ("mass", "mass_json"),
    ("family_table", "family_table_json"),
    ("features", "features_json"),  # packed: features, structure, simp reps, constraints, relations, sketch
    ("bom", "bom_json"),
)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def raw_from_version(version: ObjectVersion, parameters: list[dict]) -> dict:
    """Decoded metadata of one version (the shape stored in a baseline and read by the pages)."""
    data: dict[str, Any] = {key: _loads(getattr(version, column, None)) for key, column in _FIELDS}
    data["parameters"] = parameters
    return data


def parameters_by_version(session: Session, version_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {version_id: [] for version_id in version_ids}
    if not version_ids:
        return out
    rows = session.scalars(
        select(Parameter).where(Parameter.version_id.in_(version_ids)).order_by(Parameter.name.asc())
    ).all()
    for row in rows:
        out.setdefault(row.version_id, []).append(
            {
                "name": row.name,
                "value": row.value,
                "data_type": row.data_type or "STRING",
                "units": row.units,
                "description": row.description,
                "is_designated": bool(row.is_designated),
            }
        )
    return out


def snapshot_versions(session: Session, versions: list[ObjectVersion]) -> dict[int, str]:
    """``{version id: JSON}`` for these versions, or "" for a version with no metadata at all."""
    params = parameters_by_version(session, [v.id for v in versions])
    out: dict[int, str] = {}
    for version in versions:
        data = raw_from_version(version, params.get(version.id, []))
        has_any = any(value for value in data.values())
        out[version.id] = json.dumps(data, separators=(",", ":")) if has_any else ""
    return out
