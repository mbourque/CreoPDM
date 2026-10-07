"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

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

_DROP_PARAM_NAMES = frozenset(
    {
        "MC_INERTIA_1",
        "MC_INERTIA_2",
        "MC_INERTIA_3",
        "MC_VOLUME",
        "MC_AREA",
    }
)
# Drawing counters / lists are rendered as Views / Sheets / Referenced models.
_DRAWING_SYNTHETIC_PARAMS = frozenset(
    {
        "NUMBER_OF_VIEWS",
        "NUMBER_OF_VISIBLE_VIEWS",
        "NUMBER_OF_ERASED_VIEWS",
        "NUMBER_OF_SHEETS",
        "VIEW_NAMES",
    }
)
_KEEP_ZERO_PARAMS = _DRAWING_SYNTHETIC_PARAMS


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


def _feature_type_label(feat: dict[str, Any]) -> str:
    return str(feat.get("type") or feat.get("subtype") or "").strip().upper()


def _is_pattern_feature(feat: dict[str, Any]) -> bool:
    name = str(feat.get("name") or "").strip().upper()
    return _feature_type_label(feat) == "PATTERN" or name == "PATTERN"


def _is_view_feature(feat: dict[str, Any]) -> bool:
    return _feature_type_label(feat) == "VIEW"


def _is_pattern_placeholder_feature(feat: dict[str, Any]) -> bool:
    """True for Creo pattern-member shells that drown solid compares."""
    if not isinstance(feat, dict):
        return False
    if _is_pattern_feature(feat):
        return False
    if _feature_type_label(feat):
        return False
    name = str(feat.get("name") or "").strip()
    if not name:
        return True
    return bool(_PLACEHOLDER_FEATURE_NAME.match(name))


def _iter_compare_features(features: list[Any]) -> list[dict[str, Any]]:
    """Real features only; pattern-member shells collapsed onto PATTERN heads."""
    out: list[dict[str, Any]] = []
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
        if _is_pattern_feature(feat):
            j = i + 1
            while j < n and isinstance(features[j], dict) and _is_pattern_placeholder_feature(
                features[j]
            ):
                j += 1
            out.append(feat)
            i = j
            continue
        out.append(feat)
        i += 1
    if orphan_placeholders:
        out.append({"name": "PATTERN", "type": "PATTERN"})
    return out


def _is_drawing_snapshot(snapshot: dict[str, Any], identity: dict[str, Any]) -> bool:
    model_type = str(identity.get("model_type") or "").strip().upper()
    filename = str(identity.get("filename") or "").strip().lower()
    if model_type == "DRAWING" or filename.endswith(".drw"):
        return True
    capture = snapshot.get("capture") if isinstance(snapshot.get("capture"), dict) else {}
    if capture.get("sheet_count") is not None or capture.get("drawing_models"):
        return True
    features = snapshot.get("features")
    if isinstance(features, list) and any(
        isinstance(f, dict) and _is_view_feature(f) for f in features
    ):
        return True
    return False


def _view_display_line(feat: dict[str, Any]) -> str:
    name = str(feat.get("name") or "").strip() or "unnamed view"
    extras: list[str] = []
    subtype = str(feat.get("subtype") or "").strip()
    if subtype and subtype.upper() not in {"VIEW", name.upper()}:
        extras.append(subtype)
    if feat.get("erased") is True or str(feat.get("status") or "").lower() == "erased":
        extras.append("erased")
    sheet = feat.get("sheet")
    if sheet not in (None, ""):
        extras.append(f"sheet {sheet}")
    scale = feat.get("scale")
    if scale not in (None, ""):
        extras.append(f"scale {scale}")
    model = str(feat.get("model") or "").strip()
    if model:
        extras.append(f"model {model}")
    if feat.get("is_background") is True:
        extras.append("background")
    if extras:
        return f"- {name} ({', '.join(extras)})"
    return f"- {name}"


def _feature_display_name(feat: dict[str, Any]) -> str:
    if _is_view_feature(feat):
        return _view_display_line(feat).lstrip("- ").strip()
    name = str(feat.get("name") or "").strip()
    ftype = str(feat.get("type") or "").strip()
    subtype = str(feat.get("subtype") or "").strip()
    if not name or _PLACEHOLDER_FEATURE_NAME.match(name):
        name = subtype or ftype or "unnamed feature"
    if name.upper() in {"PATTERN", "EXTRUDE"} or name.upper() == ftype.upper():
        return name
    if ftype and ftype.upper() not in name.upper():
        return f"{name} ({ftype})"
    return name


def _format_dim_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value).strip()


def _iter_compare_dimensions(dimensions: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        dim_type = str(dim.get("dim_type") or "").strip().upper()
        try:
            dim_val = float(dim.get("value"))
        except (TypeError, ValueError):
            dim_val = None
        if dim_type == "ITEM_DIMENSION":
            continue
        if dim_val == 0.0 and dim.get("feature_id") is not None:
            continue
        symbol = str(dim.get("symbol") or "").strip()
        if not symbol:
            continue
        out.append(dim)
    return out


def _iter_compare_parameters(
    parameters: list[Any], *, drawing: bool = False
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for param in parameters:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        if not name:
            continue
        name_u = name.upper()
        owner = str(param.get("owner") or "").strip().lower()
        if owner.startswith("feature:"):
            continue
        if name_u.startswith("BUW_"):
            continue
        if drawing and (
            name_u in _DRAWING_SYNTHETIC_PARAMS or name_u.startswith("DRAWING_MODEL_")
        ):
            # Surfaced under Views / Sheets / Referenced models instead.
            continue
        if name_u in _DROP_PARAM_NAMES and _is_empty_value(param.get("value")):
            continue
        if name_u.startswith("MC_") and _is_empty_value(param.get("value")):
            continue
        if name_u.startswith("PTC_UNITS_"):
            continue
        if _is_empty_value(param.get("value")) and name_u not in _KEEP_ZERO_PARAMS:
            continue
        out.append(param)
    return out


def _param_lookup(parameters: list[Any], name: str) -> Any:
    want = name.upper()
    for param in parameters:
        if not isinstance(param, dict):
            continue
        if str(param.get("name") or "").strip().upper() == want:
            return param.get("value")
    return None


def slim_snapshot_for_compare(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Structured filter used by tests / tooling (Ask AI uses the text outline)."""
    if not isinstance(snapshot, dict):
        return {}
    out: dict[str, Any] = {}
    identity = snapshot.get("identity")
    if isinstance(identity, dict):
        out["identity"] = {
            key: identity[key]
            for key in ("filename", "model_type", "generic_name", "instance_name", "units")
            if key in identity and not _is_empty_value(identity.get(key))
        }
    drawing = _is_drawing_snapshot(snapshot, identity if isinstance(identity, dict) else {})
    features = snapshot.get("features")
    if isinstance(features, list):
        out["features"] = []
        for f in _iter_compare_features(features):
            row = {
                "name": str(f.get("name") or "").strip() or None,
                "type": str(f.get("type") or "").strip() or None,
                "subtype": str(f.get("subtype") or "").strip() or None,
                "status": f.get("status"),
                "erased": f.get("erased"),
                "sheet": f.get("sheet"),
                "scale": f.get("scale"),
                "model": f.get("model"),
                "is_background": f.get("is_background"),
            }
            out["features"].append({k: v for k, v in row.items() if v is not None})
    dimensions = snapshot.get("dimensions")
    if isinstance(dimensions, list):
        out["dimensions"] = [
            {
                "symbol": d.get("symbol"),
                "value": d.get("value"),
                "units": d.get("units"),
            }
            for d in _iter_compare_dimensions(dimensions)
        ]
    parameters = snapshot.get("parameters")
    if isinstance(parameters, list):
        out["parameters"] = [
            {"name": p.get("name"), "value": p.get("value")}
            for p in _iter_compare_parameters(parameters, drawing=drawing)
        ]
    materials = snapshot.get("materials")
    if isinstance(materials, dict) and (
        materials.get("current") or materials.get("names")
    ):
        out["materials"] = {
            "current": materials.get("current"),
            "names": list(materials.get("names") or []),
        }
    capture = snapshot.get("capture")
    if isinstance(capture, dict):
        slim_cap: dict[str, Any] = {}
        if capture.get("sheet_count") is not None:
            slim_cap["sheet_count"] = capture.get("sheet_count")
        if capture.get("drawing_models"):
            slim_cap["drawing_models"] = capture.get("drawing_models")
        if slim_cap:
            out["capture"] = slim_cap
    return out


def format_snapshot_compare_text(snapshot: dict[str, Any] | None) -> str:
    """Plain-language outline for Ollama (solids + drawings)."""
    if not isinstance(snapshot, dict):
        return "(empty snapshot)"
    lines: list[str] = []
    identity = snapshot.get("identity") if isinstance(snapshot.get("identity"), dict) else {}
    filename = str(identity.get("filename") or "").strip()
    model_type = str(identity.get("model_type") or "").strip()
    drawing = _is_drawing_snapshot(snapshot, identity)
    if filename or model_type:
        if filename and model_type:
            lines.append(f"Model: {filename} ({model_type})")
        elif filename:
            lines.append(f"Model: {filename}")
        else:
            lines.append(f"Model type: {model_type}")

    units = identity.get("units") if isinstance(identity.get("units"), dict) else None
    if not units and isinstance(snapshot.get("units"), dict):
        units = snapshot.get("units")
    if isinstance(units, dict):
        length = str(units.get("length") or "").strip()
        if length:
            lines.append(f"Length units: {length}")

    capture = snapshot.get("capture") if isinstance(snapshot.get("capture"), dict) else {}
    parameters = snapshot.get("parameters") if isinstance(snapshot.get("parameters"), list) else []
    features_raw = snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
    features = _iter_compare_features(features_raw)

    if drawing:
        sheet_count = capture.get("sheet_count")
        if sheet_count is None:
            sheet_count = _param_lookup(parameters, "NUMBER_OF_SHEETS")
        if sheet_count is not None and str(sheet_count).strip() != "":
            lines.append(f"Sheets: {sheet_count}")

        drawing_models = capture.get("drawing_models")
        model_lines: list[str] = []
        if isinstance(drawing_models, list) and drawing_models:
            for row in drawing_models:
                if not isinstance(row, dict):
                    continue
                fn = str(row.get("filename") or "").strip()
                mt = str(row.get("model_type") or "").strip()
                if not fn:
                    continue
                model_lines.append(f"- {fn}" + (f" ({mt})" if mt else ""))
        else:
            for param in parameters:
                if not isinstance(param, dict):
                    continue
                pname = str(param.get("name") or "").strip().upper()
                if not pname.startswith("DRAWING_MODEL_"):
                    continue
                val = str(param.get("value") or "").strip()
                if val:
                    model_lines.append(f"- {val}")
        if model_lines:
            lines.append("Referenced models:")
            lines.extend(model_lines)

        views = [f for f in features if _is_view_feature(f)]
        other = [f for f in features if not _is_view_feature(f)]
        lines.append("Views:")
        if views:
            lines.extend(_view_display_line(v) for v in views)
            visible = sum(
                1
                for v in views
                if not (
                    v.get("erased") is True
                    or str(v.get("status") or "").lower() == "erased"
                )
            )
            erased = len(views) - visible
            lines.append(f"View count: {len(views)} total, {visible} visible, {erased} erased")
        else:
            # Fallback when views were not gathered as features.
            view_names = str(_param_lookup(parameters, "VIEW_NAMES") or "").strip()
            n_total = _param_lookup(parameters, "NUMBER_OF_VIEWS")
            n_vis = _param_lookup(parameters, "NUMBER_OF_VISIBLE_VIEWS")
            n_er = _param_lookup(parameters, "NUMBER_OF_ERASED_VIEWS")
            if view_names:
                for part in [p.strip() for p in view_names.split(",") if p.strip()]:
                    lines.append(f"- {part}")
            else:
                lines.append("- (none)")
            if n_total is not None:
                bits = [f"{n_total} total"]
                if n_vis is not None:
                    bits.append(f"{n_vis} visible")
                if n_er is not None:
                    bits.append(f"{n_er} erased")
                lines.append("View count: " + ", ".join(bits))

        if other:
            lines.append("Other features:")
            lines.extend(f"- {_feature_display_name(f)}" for f in other)
    else:
        lines.append("Features:")
        if features:
            lines.extend(f"- {_feature_display_name(f)}" for f in features)
        else:
            lines.append("- (none)")

    dimensions = snapshot.get("dimensions")
    if isinstance(dimensions, list):
        dim_lines: list[str] = []
        for dim in _iter_compare_dimensions(dimensions):
            symbol = str(dim.get("symbol") or "").strip()
            value = _format_dim_value(dim.get("value"))
            unit = str(dim.get("units") or "").strip()
            piece = f"- {symbol} = {value}"
            if unit:
                piece += f" {unit}"
            limits = dim.get("tolerance_limits")
            if isinstance(limits, dict) and limits:
                lo = limits.get("lower", limits.get("min"))
                hi = limits.get("upper", limits.get("max"))
                if lo is not None and hi is not None:
                    piece += (
                        f" (limits {_format_dim_value(lo)}–{_format_dim_value(hi)})"
                    )
            dim_lines.append(piece)
        lines.append("Dimensions:")
        lines.extend(dim_lines or ["- (none)"])

    if not drawing:
        materials = snapshot.get("materials")
        if isinstance(materials, dict):
            current = str(materials.get("current") or "").strip()
            names = [
                str(n).strip()
                for n in (materials.get("names") or [])
                if str(n).strip()
            ]
            if current or names:
                if current:
                    lines.append(f"Material: {current}")
                elif len(names) == 1:
                    lines.append(f"Material: {names[0]}")
                else:
                    lines.append("Materials: " + ", ".join(names))

    param_rows = _iter_compare_parameters(parameters, drawing=drawing)
    if param_rows or drawing:
        # Always show Parameters for drawings when other model params exist;
        # skip empty "(none)" noise when drawing synthetics were the only ones.
        if param_rows:
            lines.append("Parameters:")
            for param in param_rows:
                name = str(param.get("name") or "").strip()
                value = param.get("value")
                if isinstance(value, str):
                    value_s = value.strip()
                else:
                    value_s = _format_dim_value(value)
                lines.append(f"- {name} = {value_s}")
        elif not drawing:
            lines.append("Parameters:")
            lines.append("- (none)")

    return "\n".join(lines) if lines else "(empty snapshot)"


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: OLD then NEW plain-language outlines (settings hold instructions)."""
    older_label = (older_revision or "").strip()
    newer_label = (newer_revision or "").strip()
    if not older_label or older_label in {"—", "-"}:
        older_label = "older"
    if not newer_label or newer_label in {"—", "-"}:
        newer_label = "newer"
    older_text = format_snapshot_compare_text(older_snapshot)
    newer_text = format_snapshot_compare_text(newer_snapshot)
    return (
        f"Two snapshots follow. The first is OLD (already checked in); "
        f"the second is NEW (the revision being compared / checked in). "
        f"Do not swap them. Compare OLD ({older_label}) → NEW ({newer_label}).\n\n"
        f"=== OLD snapshot ({older_label}) ===\n"
        f"{older_text}\n\n"
        f"=== NEW snapshot ({newer_label}) ===\n"
        f"{newer_text}\n\n"
        f"Summarize only what changed from OLD ({older_label}) to NEW ({newer_label}), "
        f"following your instructions. Treat the block under "
        f"\"=== OLD snapshot ===\" as the previous state and "
        f"\"=== NEW snapshot ===\" as the current state. "
        f"Never claim a revision is missing when both revision outlines are present above."
    )
