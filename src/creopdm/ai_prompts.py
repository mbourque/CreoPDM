"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

import json
from typing import Any

from creopdm.exceptions import ValidationAppError

# Drawing view Outline floats / revision meta bloat Ollama prompts. Large solids
# (100+ features) used to overflow context so the model only "saw" the newer JSON
# and claimed A.1 was missing.
_FEATURE_KEEP = (
    "id",
    "name",
    "type",
    "subtype",
    "status",
    "regen_order",
    "parent_ids",
    "group_id",
    "pattern_id",
    "sheet",
    "scale",
    "model",
    "erased",
    "is_background",
)
_DIM_KEEP = (
    "id",
    "symbol",
    "value",
    "units",
    "feature_id",
    "dim_type",
    "extends_negative",
    "tolerance_type",
    "tolerance_limits",
    "relation_driven",
)
_PARAM_KEEP = ("name", "value", "data_type", "units", "owner", "description")
_CAPTURE_KEEP = (
    "status",
    "errors",
    "sheet_count",
    "drawing_models",
    "assembly_context",
)
_DROP_PARAM_NAMES = frozenset(
    {
        "MC_INERTIA_1",
        "MC_INERTIA_2",
        "MC_INERTIA_3",
        "MC_VOLUME",
        "MC_AREA",
    }
)


def resolve_snapshot_compare_prompt(saved: str | None) -> str:
    """Require the Administration → AI snapshot compare prompt (no code fallback)."""
    text = str(saved or "").strip()
    if not text:
        raise ValidationAppError(
            "No snapshot compare prompt is saved. Open Administration → AI, "
            "paste your prompt, and Save."
        )
    return text


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if value is None:
            continue
        if key in {"parent_ids", "errors"} and value == []:
            continue
        if key == "erased" and value is None:
            continue
        out[key] = value
    return out


def slim_snapshot_for_compare(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Copy a snapshot for Ollama — compact fields so older+newer both fit in context."""
    if not isinstance(snapshot, dict):
        return {}
    out: dict[str, Any] = {"schema_version": snapshot.get("schema_version", 1)}
    identity = snapshot.get("identity")
    if isinstance(identity, dict):
        out["identity"] = {
            key: identity[key]
            for key in (
                "filename",
                "model_type",
                "generic_name",
                "instance_name",
                "units",
            )
            if key in identity and not _is_empty_value(identity.get(key))
        }

    features = snapshot.get("features")
    if isinstance(features, list):
        slim_feats = []
        for feat in features:
            if not isinstance(feat, dict):
                continue
            row = _pick(feat, _FEATURE_KEEP)
            if row:
                slim_feats.append(row)
        out["features"] = slim_feats

    dimensions = snapshot.get("dimensions")
    if isinstance(dimensions, list):
        slim_dims = []
        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            row = _pick(dim, _DIM_KEEP)
            if row:
                slim_dims.append(row)
        out["dimensions"] = slim_dims

    parameters = snapshot.get("parameters")
    if isinstance(parameters, list):
        slim_params = []
        for param in parameters:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip().upper()
            if name in _DROP_PARAM_NAMES and _is_empty_value(param.get("value")):
                continue
            if name.startswith("MC_") and _is_empty_value(param.get("value")):
                continue
            if name.startswith("PTC_UNITS_"):
                # Units already on identity / units block.
                continue
            row = _pick(param, _PARAM_KEEP)
            if row and not _is_empty_value(row.get("value")):
                slim_params.append(row)
            elif row and str(row.get("name") or "").upper() in {
                "NUMBER_OF_VIEWS",
                "NUMBER_OF_VISIBLE_VIEWS",
                "NUMBER_OF_ERASED_VIEWS",
                "NUMBER_OF_SHEETS",
                "VIEW_NAMES",
            }:
                # Keep drawing counters even when value is 0.
                slim_params.append(row)
        out["parameters"] = slim_params

    materials = snapshot.get("materials")
    if isinstance(materials, dict) and (
        materials.get("current") or materials.get("names")
    ):
        out["materials"] = {
            "current": materials.get("current"),
            "names": list(materials.get("names") or []),
        }

    units = snapshot.get("units")
    if isinstance(units, dict) and any(str(v or "").strip() for v in units.values()):
        out["units"] = units

    family = snapshot.get("family_table")
    if isinstance(family, dict) and (family.get("columns") or family.get("rows")):
        out["family_table"] = family

    capture = snapshot.get("capture")
    if isinstance(capture, dict):
        slim_cap = _pick(capture, _CAPTURE_KEEP)
        if slim_cap:
            out["capture"] = slim_cap
    return out


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: older then newer JSON only (instructions come from AI settings)."""
    older_label = (older_revision or "").strip() or "older"
    newer_label = (newer_revision or "").strip() or "newer"
    # Compact JSON — indent=2 roughly doubles tokens and pushed large parts past context.
    older_json = json.dumps(
        slim_snapshot_for_compare(older_snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    newer_json = json.dumps(
        slim_snapshot_for_compare(newer_snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return (
        f"Both revisions below are required. Compare {older_label} → {newer_label}.\n\n"
        f"Older revision ({older_label}):\n{older_json}\n\n"
        f"Newer revision ({newer_label}):\n{newer_json}\n\n"
        f"Summarize what changed from {older_label} to {newer_label}, "
        f"following your instructions. Never claim a revision is missing when both "
        f"JSON blocks are present above."
    )
