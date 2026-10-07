"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

import json
import re
from typing import Any

from creopdm.exceptions import ValidationAppError

# Creo pattern members often land as "Feature 15775" / IFX_ID_* with empty type.
# Sending hundreds of those to Ollama blew the context so Ask AI said "no changes"
# even when a whole PATTERN head was deleted.
_PLACEHOLDER_FEATURE_NAME = re.compile(
    r"^(?:feature\s+\d+|ifx_id_\d+|no_name)$",
    re.IGNORECASE,
)

# Drawing view Outline floats / revision meta bloat Ollama prompts. Large solids
# (100+ features) used to overflow context so the model only "saw" the newer JSON
# and claimed A.1 was missing.
# No feature/dim ids in the Ollama payload — models were citing "feature 15775".
_FEATURE_KEEP = (
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
    "symbol",
    "value",
    "units",
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


def _feature_type_label(feat: dict[str, Any]) -> str:
    return str(feat.get("type") or feat.get("subtype") or "").strip().upper()


def _is_pattern_feature(feat: dict[str, Any]) -> bool:
    name = str(feat.get("name") or "").strip().upper()
    return _feature_type_label(feat) == "PATTERN" or name == "PATTERN"


def _is_pattern_placeholder_feature(feat: dict[str, Any]) -> bool:
    """True for Creo pattern-member shells that drown solid compares."""
    if not isinstance(feat, dict):
        return False
    if _is_pattern_feature(feat):
        return False
    # Typed geometry / drawing views stay intact (incl. DATUM named no_name).
    if _feature_type_label(feat):
        return False
    name = str(feat.get("name") or "").strip()
    if not name:
        return True
    return bool(_PLACEHOLDER_FEATURE_NAME.match(name))


def _slim_features_for_compare(features: list[Any]) -> list[dict[str, Any]]:
    """Keep real features; fold pattern-member placeholders into pattern_member_count."""
    slim: list[dict[str, Any]] = []
    orphan_placeholders = 0
    i = 0
    n = len(features)
    while i < n:
        feat = features[i]
        if not isinstance(feat, dict):
            i += 1
            continue
        if _is_pattern_placeholder_feature(feat):
            orphan_placeholders += 1
            i += 1
            continue
        row = _pick(feat, _FEATURE_KEEP)
        if not row:
            i += 1
            continue
        if _is_pattern_feature(feat):
            member_count = 0
            j = i + 1
            while j < n and isinstance(features[j], dict) and _is_pattern_placeholder_feature(
                features[j]
            ):
                member_count += 1
                j += 1
            # Keep heads only — do not expose member totals (models quoted
            # "pattern_member_total from 1062 to 50" instead of "deleted a pattern").
            if member_count:
                row["has_pattern_members"] = True
            slim.append(row)
            i = j
            continue
        slim.append(row)
        i += 1
    if orphan_placeholders:
        slim.append({"name": "PATTERN", "type": "PATTERN", "has_pattern_members": True})
    return slim


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
        out["features"] = _slim_features_for_compare(features)

    dimensions = snapshot.get("dimensions")
    if isinstance(dimensions, list):
        slim_dims = []
        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            # Pattern item dims (value 0 / ITEM_DIMENSION) vanish with the pattern
            # and made Ask AI invent "Removed dimension d253 … feature 15775."
            dim_type = str(dim.get("dim_type") or "").strip().upper()
            try:
                dim_val = float(dim.get("value"))
            except (TypeError, ValueError):
                dim_val = None
            if dim_type == "ITEM_DIMENSION":
                continue
            if dim_val == 0.0 and dim.get("feature_id") is not None:
                continue
            row = _pick(dim, _DIM_KEEP)
            if row:
                slim_dims.append(row)
        out["dimensions"] = slim_dims

    parameters = snapshot.get("parameters")
    if isinstance(parameters, list):
        slim_params = []
        keep_zero = {
            "NUMBER_OF_VIEWS",
            "NUMBER_OF_VISIBLE_VIEWS",
            "NUMBER_OF_ERASED_VIEWS",
            "NUMBER_OF_SHEETS",
            "VIEW_NAMES",
        }
        for param in parameters:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip().upper()
            owner = str(param.get("owner") or "").strip().lower()
            # Feature-owned params (BUW_ID, hole tables, …) drown real feature
            # diffs and made the model invent "HOLE_CLEARANCE features."
            if owner.startswith("feature:"):
                continue
            if name.startswith("BUW_"):
                continue
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
            elif row and name in keep_zero:
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
    older_label = (older_revision or "").strip()
    newer_label = (newer_revision or "").strip()
    if not older_label or older_label in {"—", "-"}:
        older_label = "older"
    if not newer_label or newer_label in {"—", "-"}:
        newer_label = "newer"
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
