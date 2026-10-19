"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from creopdm.exceptions import ValidationAppError
from creopdm.toolkit_snapshot import nest_drawing_inventory_by_sheet
from creopdm.utils.bom_match import normalize_bom_compare_filename
from creopdm.utils.mass_format import format_mass_value

# Creo pattern members often land as "Feature 15775" / IFX_ID_* with empty type.
# Sending hundreds of those to Ollama blew the context so Ask AI said "no changes"
# even when a whole PATTERN head was deleted.
_PLACEHOLDER_FEATURE_NAME = re.compile(
    r"^(?:feature\s+\d+|ifx_id_\d+|no_name)$",
    re.IGNORECASE,
)
# Trailing Creo feature id on outline lines: "CUT (95)" / "RIGHT (DATUM PLANE) (39)".
_OUTLINE_FEATURE_ID_SUFFIX = re.compile(r"\((\d+)\)\s*$")

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
    """Require the System Settings → AI snapshot compare prompt (no code fallback)."""
    text = str(saved or "").strip()
    if not text:
        raise ValidationAppError(
            "No snapshot compare prompt is saved. Open System Settings → AI, "
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


# Drawing inventory rows that are containers / already covered by Dimensions:.
_DRAWING_INVENTORY_SKIP_COMPARE = frozenset(
    {"SHEET", "DRAWING", "DIMENSION", "DIM", "ITEM_DIMENSION"}
)


_DRAWING_DIM_TYPES = frozenset({"DIMENSION", "DIM", "ITEM_DIMENSION"})


def _snapshot_has_dimension_list(snapshot: dict[str, Any]) -> bool:
    dims = snapshot.get("dimensions")
    return isinstance(dims, list) and bool(_iter_compare_dimensions(dims))


def _is_drawing_inventory_compare_feature(
    feat: dict[str, Any], *, dims_listed: bool = True
) -> bool:
    """Views / notes / tables / detail items — not sheet shells or dim duplicates.

    Drawings get their dimensions only as DIMENSION inventory rows (the Toolkit sends no
    separate dimensions list), so those rows stay in unless a real list covers them.
    """
    if not isinstance(feat, dict):
        return False
    typ = _feature_type_label(feat)
    if typ in _DRAWING_DIM_TYPES and not dims_listed:
        return True
    return typ not in _DRAWING_INVENTORY_SKIP_COMPARE


def _drawing_has_rich_inventory(features: list[dict[str, Any]]) -> bool:
    """True when snapshot features include inventory beyond legacy VIEW-only rows."""
    for feat in features:
        typ = _feature_type_label(feat)
        if typ and typ not in {"VIEW", ""}:
            return True
    return False


def _inventory_level(row: dict[str, Any]) -> int:
    try:
        level = int(row.get("level")) if row.get("level") is not None else 1
    except (TypeError, ValueError):
        level = 1
    return level if level > 0 else 1


def _append_creo_feature_id(label: str, feat: dict[str, Any] | None) -> str:
    """Ensure outline text ends with Creo feature id when known (compare matches on id)."""
    text = str(label or "")
    if not text.strip() or not isinstance(feat, dict):
        return text
    fid = _norm_feature_id(feat.get("id"))
    if not fid:
        return text
    # Keep leading indent (structure / drawing inventory nesting).
    core = text.rstrip()
    match = _OUTLINE_FEATURE_ID_SUFFIX.search(core)
    if match:
        if match.group(1) == fid:
            return core
        return _OUTLINE_FEATURE_ID_SUFFIX.sub(f"({fid})", core)
    return f"{core} ({fid})"


def _outline_status_extra(status: str) -> str | None:
    """Statuses shown on Structure/Features outline lines.

    SIMP_REP_* is active-representation capture context — never outline it as a
    Structure status (Ask AI will invent "suppressed removed / components added").
    Active + definitions belong only in the Simplified representations block.
    """
    text = str(status or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper in {"ACTIVE", ""}:
        return None
    if upper.startswith("SIMP_REP"):
        return None
    return text


def _inventory_outline_line(row: dict[str, Any]) -> str:
    """Indented inventory line (same nesting idea as Details inventory tables)."""
    name = str(row.get("name") or "").strip() or "—"
    typ = str(row.get("type") or "").strip()
    status = _outline_status_extra(str(row.get("status") or ""))
    level = _inventory_level(row)
    indent = "  " * max(0, level - 1)
    nest = "└ " if level > 1 else ""
    extras: list[str] = []
    detail = str(row.get("detail") or "").strip()
    dim_kind = str(row.get("subtype") or row.get("subType") or "").strip()
    if typ.upper() == "DIMENSION" and (dim_kind or detail):
        # kind (LINEAR / ANGLE / RADIUS) instead of the word DIMENSION
        extras.append(dim_kind or detail)
    elif typ and typ.upper() not in name.upper():
        extras.append(typ)
    if status:
        extras.append(status)
    sheet = row.get("sheet")
    if sheet not in (None, "") and typ.upper() != "SHEET":
        extras.append(f"sheet {sheet}")
    if detail and typ.upper() == "NOTE":
        short = detail if len(detail) <= 80 else detail[:77] + "…"
        extras.append(short)
    suffix = f" ({', '.join(extras)})" if extras else ""
    value_text = _drawing_dimension_value_text(row) if typ.upper() == "DIMENSION" else ""
    if value_text:
        suffix += f" = {value_text}"
    return _append_creo_feature_id(f"{indent}- {nest}{name}{suffix}", row)


def _drawing_dimension_value_text(row: dict[str, Any]) -> str:
    """``30 deg (limits 29.5–30.5) [shows 30.0]`` — exact value; displayed text is display only."""
    value = row.get("value")
    if value is None or value == "":
        return ""
    piece = _format_dim_value(value)
    unit = str(row.get("units") or "").strip()
    if unit:
        piece += f" {unit}"
    limits = row.get("tolerance_limits")
    if isinstance(limits, dict) and limits:
        lo = limits.get("lower", limits.get("min"))
        hi = limits.get("upper", limits.get("max"))
        if lo is not None and hi is not None:
            piece += f" (limits {_format_dim_value(lo)}–{_format_dim_value(hi)})"
    shown = str(row.get("value_displayed") or "").strip()
    if shown and shown != _format_dim_value(value):
        piece += f" [shows {shown}]"
    return piece


def _drawing_dimension_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Drawing DIMENSION inventory rows as dimension dicts for the OLD→NEW diff.

    Keyed by the Creo id (``dim:wedge.prt:2``) so the same name on two models cannot merge.
    Value is the exact number; ``value_displayed`` is never compared.
    """
    features = snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
    rows = [
        f
        for f in features
        if isinstance(f, dict) and _feature_type_label(f) in _DRAWING_DIM_TYPES
    ]
    names = [str(f.get("name") or "").strip() for f in rows]
    out: list[dict[str, Any]] = []
    for feat, name in zip(rows, names):
        if not name:
            continue
        creo_id = str(feat.get("id") or "").strip()
        symbol = f"{name} [{creo_id}]" if names.count(name) > 1 and creo_id else name
        dim: dict[str, Any] = {
            "symbol": symbol,
            "dim_type": str(feat.get("subtype") or feat.get("subType") or "").strip(),
        }
        has_value = feat.get("value") is not None and feat.get("value") != ""
        # "—" = not collected yet (older revision): equal on both sides, so no false change.
        dim["value"] = feat["value"] if has_value else "—"
        unit = str(feat.get("units") or "").strip()
        if unit:
            dim["units"] = unit
        if isinstance(feat.get("tolerance_limits"), dict):
            dim["tolerance_limits"] = feat["tolerance_limits"]
        out.append(dim)
    return out


def _compare_dimension_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The real dimensions list, or (drawings) the DIMENSION inventory rows."""
    dims = snapshot.get("dimensions")
    if isinstance(dims, list) and _iter_compare_dimensions(dims):
        return _iter_compare_dimensions(dims)
    identity = snapshot.get("identity") if isinstance(snapshot.get("identity"), dict) else {}
    if _is_drawing_snapshot(snapshot, identity):
        return _iter_compare_dimensions(_drawing_dimension_rows(snapshot))
    return []


def _structure_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    structure = snapshot.get("structure")
    if not isinstance(structure, list):
        return []
    return [row for row in structure if isinstance(row, dict) and str(row.get("name") or "").strip()]


def _structure_compare_label(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip() or "—"
    typ = str(row.get("type") or "").strip()
    path = str(row.get("path") or "").strip()
    key = path or name
    if typ and typ.upper() not in {"COMPONENT", ""}:
        return f"{key} ({typ})"
    return key


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


def _is_invisible_or_pattern_internal_feature(feat: dict[str, Any]) -> bool:
    """Skip Creo internals that are not in the model tree (false plane deletes)."""
    if not isinstance(feat, dict):
        return True
    if feat.get("visible") is False:
        return True
    if _is_pattern_feature(feat):
        return False
    pattern_id = feat.get("pattern_id")
    if pattern_id is not None and str(pattern_id).strip() != "":
        # Owned by a pattern but not the PATTERN head — construction/member.
        return True
    return False


def _iter_compare_features(features: list[Any]) -> list[dict[str, Any]]:
    """Real features only; pattern-member shells collapsed onto PATTERN heads.

    Standalone ``Feature 189`` / empty-type rows (no PATTERN head) stay as
    themselves — matching the Features tab. Do **not** invent a synthetic
    PATTERN from those orphans (that made Ask AI claim a pattern add when the
    tree only had an unnamed feature).
    """
    out: list[dict[str, Any]] = []
    i = 0
    n = len(features)
    while i < n:
        feat = features[i]
        if not isinstance(feat, dict):
            i += 1
            continue
        if _is_invisible_or_pattern_internal_feature(feat):
            i += 1
            continue
        if _is_pattern_feature(feat):
            j = i + 1
            while j < n and isinstance(features[j], dict) and (
                _is_pattern_placeholder_feature(features[j])
                or _is_invisible_or_pattern_internal_feature(features[j])
            ):
                j += 1
            member_count = j - i - 1
            head = dict(feat)
            if member_count > 0:
                head["pattern_member_count"] = member_count
            out.append(head)
            i = j
            continue
        # Keep standalone Feature NNNN / IFX_ID_* (Features tab shows them).
        out.append(feat)
        i += 1
    return out


def _pattern_outline_label(feat: dict[str, Any], *, index: int) -> str:
    """Number PATTERNs in tree order so OLD vs NEW can name which one was removed."""
    label = f"PATTERN {index}"
    members = feat.get("pattern_member_count")
    try:
        count = int(members) if members is not None else 0
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return f"{label} ({count} members)"
    return label


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


def _is_assembly_snapshot(snapshot: dict[str, Any], identity: dict[str, Any]) -> bool:
    model_type = str(identity.get("model_type") or "").strip().upper()
    filename = str(identity.get("filename") or "").strip().lower()
    if model_type == "ASSEMBLY" or filename.endswith(".asm"):
        return True
    bom = snapshot.get("bom")
    return isinstance(bom, list) and bool(bom)


def _bom_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    bom = snapshot.get("bom")
    if not isinstance(bom, list):
        return []
    return [node for node in bom if isinstance(node, dict)]


def _bom_qty(value: Any) -> int:
    try:
        qty = int(value) if value is not None else 1
    except (TypeError, ValueError):
        qty = 1
    return qty if qty > 0 else 1


def _format_bom_outline_lines(
    nodes: list[dict[str, Any]], *, depth: int = 0
) -> list[str]:
    """Plain Structure tree (same qty rules as Details Structure tab)."""
    lines: list[str] = []
    for node in nodes:
        raw = str(node.get("filename") or "").strip()
        name = normalize_bom_compare_filename(raw) or raw or "—"
        qty = _bom_qty(node.get("quantity"))
        indent = "  " * depth
        if qty != 1:
            lines.append(f"{indent}- {name} × {qty}")
        else:
            lines.append(f"{indent}- {name}")
        children = node.get("children")
        if isinstance(children, list) and children:
            child_nodes = [c for c in children if isinstance(c, dict)]
            lines.extend(_format_bom_outline_lines(child_nodes, depth=depth + 1))
    return lines


def _bom_member_qty_map(
    nodes: list[dict[str, Any]], *, path: tuple[str, ...] = ()
) -> dict[str, tuple[str, int]]:
    """
    Path-keyed member quantities (skip ASSEMBLY_ROOT itself).
    key = lowercased path like 'square_tube_1.prt' or 'sub.asm/child.prt'
    value = (display_name_with_path, qty)

    Filenames are normalized so session FullName ``skel<<ASM>.prt`` matches the
    tip Structure name ``skel.prt`` (Check In Ask AI vs Modifications).
    """
    out: dict[str, tuple[str, int]] = {}
    for node in nodes:
        raw = str(node.get("filename") or "").strip()
        name = normalize_bom_compare_filename(raw) or raw
        if not name:
            continue
        name_l = name.lower()
        dep = str(node.get("dependency_type") or "").strip().upper()
        qty = _bom_qty(node.get("quantity"))
        children_raw = node.get("children")
        children = (
            [c for c in children_raw if isinstance(c, dict)]
            if isinstance(children_raw, list)
            else []
        )
        if dep == "ASSEMBLY_ROOT":
            out.update(_bom_member_qty_map(children, path=()))
            continue
        key_path = path + (name_l,)
        key = "/".join(key_path)
        display = "/".join(path + (name,)) if path else name
        prev = out.get(key)
        if prev:
            out[key] = (prev[0], prev[1] + qty)
        else:
            out[key] = (display, qty)
        if children:
            out.update(_bom_member_qty_map(children, path=key_path))
    return out


def _component_outline_label(display: str, qty: int) -> str:
    if qty != 1:
        return f"{display} × {qty}"
    return display


def _slim_bom_nodes(nodes: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("filename") or "").strip()
        if not name:
            continue
        tip_name = normalize_bom_compare_filename(name) or name
        row: dict[str, Any] = {
            "filename": tip_name,
            "quantity": _bom_qty(node.get("quantity")),
        }
        dep = str(node.get("dependency_type") or "").strip()
        if dep:
            row["dependency_type"] = dep
        children = node.get("children")
        if isinstance(children, list) and children:
            slim_children = _slim_bom_nodes(children)
            if slim_children:
                row["children"] = slim_children
        out.append(row)
    return out


def prepare_snapshot_for_compare(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """
    Canonical snapshot for Modifications panes / Ask AI / Check In comment.

    Parts, assemblies, and drawings all go through this before outline + diff
    text is built — Check In Ask AI must not use a rawer gather than Compare.
    """
    if not isinstance(snapshot, dict):
        return {}
    out = dict(snapshot)
    identity = out.get("identity")
    if isinstance(identity, dict):
        id_row = dict(identity)
        raw_fn = str(id_row.get("filename") or "").strip()
        if raw_fn:
            tip = normalize_bom_compare_filename(raw_fn) or raw_fn
            id_row["filename"] = tip
        out["identity"] = id_row
    bom = out.get("bom")
    if isinstance(bom, list) and bom:
        out["bom"] = _slim_bom_nodes(bom)
    structure = out.get("structure")
    if isinstance(structure, list) and structure:
        out["structure"] = [dict(row) for row in structure if isinstance(row, dict)]
    simp_reps = out.get("simp_reps")
    if isinstance(simp_reps, dict) and simp_reps:
        out["simp_reps"] = dict(simp_reps)
    constraints = out.get("constraints")
    if isinstance(constraints, dict) and constraints:
        out["constraints"] = dict(constraints)
    relations = out.get("relations")
    if isinstance(relations, dict) and relations:
        out["relations"] = dict(relations)
    # Stamp feature_name onto dims from feature id → name (for older snaps /
    # gathers that only stored feature_id).
    labels = _feature_id_label_map(out)
    dims = out.get("dimensions")
    if isinstance(dims, list) and labels:
        stamped: list[Any] = []
        for dim in dims:
            if not isinstance(dim, dict):
                stamped.append(dim)
                continue
            row = dict(dim)
            if not _is_usable_feature_owner_label(str(row.get("feature_name") or "")):
                owner = _dimension_owner_label(row, labels)
                if owner:
                    row["feature_name"] = owner
            stamped.append(row)
        out["dimensions"] = stamped
    # Drawings / older snaps often store dims with empty units — fill before outline.
    _fill_missing_dimension_units(out)
    return out


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


def _feature_display_name(feat: dict[str, Any], *, pattern_index: int | None = None) -> str:
    """Human label only (no forced id) — dim owner parentheses use this."""
    if _is_view_feature(feat):
        return _view_display_line(feat).lstrip("- ").strip()
    if _is_pattern_feature(feat):
        idx = pattern_index if pattern_index is not None else 1
        return _pattern_outline_label(feat, index=idx)
    name = str(feat.get("name") or "").strip()
    ftype = str(feat.get("type") or "").strip()
    subtype = str(feat.get("subtype") or "").strip()
    if not name:
        name = subtype or ftype or "unnamed feature"
    elif _PLACEHOLDER_FEATURE_NAME.match(name):
        # Prefer real type/subtype; keep Feature N / IFX_ID_* when that is all
        # Creo gave (standalone orphan — Features tab shows the same label).
        if subtype or ftype:
            name = subtype or ftype
    if name.upper() in {"EXTRUDE"} or name.upper() == ftype.upper():
        return name
    if ftype and ftype.upper() not in name.upper():
        return f"{name} ({ftype})"
    return name


def _feature_outline_label(feat: dict[str, Any], *, pattern_index: int | None = None) -> str:
    """Feature list / Ask AI outline line — always ends with Creo id when known."""
    return _append_creo_feature_id(
        _feature_display_name(feat, pattern_index=pattern_index), feat
    )


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


def _norm_feature_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(int(value))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


def _feature_id_label_map(snapshot: dict[str, Any]) -> dict[str, str]:
    """Map Creo feature id → outline label for dimension owner parentheses."""
    features_raw = (
        snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
    )
    labels: dict[str, str] = {}
    features = _iter_compare_features(features_raw)
    pattern_i = 0
    for feat in features:
        fid = _norm_feature_id(feat.get("id"))
        if not fid:
            continue
        if _is_pattern_feature(feat):
            pattern_i += 1
            labels[fid] = _feature_display_name(feat, pattern_index=pattern_i)
        else:
            labels[fid] = _feature_display_name(feat)
    # Dims on filtered members: inherit PATTERN / parent label when possible.
    for feat in features_raw:
        if not isinstance(feat, dict):
            continue
        fid = _norm_feature_id(feat.get("id"))
        if not fid or fid in labels:
            continue
        parent = _norm_feature_id(feat.get("pattern_id"))
        if parent and parent in labels:
            labels[fid] = labels[parent]
        else:
            labels[fid] = _feature_display_name(feat)
    return labels


def _is_usable_feature_owner_label(label: str) -> bool:
    """True for a human feature name — never a bare Creo feature id."""
    text = str(label or "").strip()
    if not text:
        return False
    if text.isdigit():
        return False
    if _PLACEHOLDER_FEATURE_NAME.match(text):
        return False
    return True


def _dimension_owner_label(
    dim: dict[str, Any],
    feature_labels: dict[str, str] | None,
) -> str:
    """Resolve owning feature **name** (lookup by feature_id; never print the id)."""
    if feature_labels:
        fid = _norm_feature_id(dim.get("feature_id"))
        if fid:
            mapped = str(feature_labels.get(fid) or "").strip()
            if _is_usable_feature_owner_label(mapped):
                return mapped
    for key in ("feature_name", "owner_name"):
        text = str(dim.get(key) or "").strip()
        if _is_usable_feature_owner_label(text):
            return text
    return ""


def _principal_length_angle_units(snapshot: dict[str, Any]) -> tuple[str, str]:
    """Length / angle unit names from identity or PTC_UNITS_* (drawings often lack units)."""
    length = ""
    angle = ""
    for src in (
        snapshot.get("units"),
        (snapshot.get("identity") or {}).get("units")
        if isinstance(snapshot.get("identity"), dict)
        else None,
    ):
        if not isinstance(src, dict):
            continue
        if not length:
            length = str(src.get("length") or "").strip()
        if not angle:
            angle = str(src.get("angle") or "").strip()
    params = snapshot.get("parameters")
    if isinstance(params, list):
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip().upper()
            val = str(param.get("value") or "").strip()
            if not val:
                continue
            if name == "PTC_UNITS_LENGTH" and not length:
                length = val
            elif name in {"PTC_UNITS_ANGLE", "PTC_UNIT_ANGLE"} and not angle:
                angle = val
    return length, angle


def _fill_missing_dimension_units(snapshot: dict[str, Any]) -> None:
    """Backfill empty dim.units so Compare/Ask AI never shows a bare number."""
    dims = snapshot.get("dimensions")
    if not isinstance(dims, list) or not dims:
        return
    length, angle = _principal_length_angle_units(snapshot)
    filled: list[Any] = []
    for dim in dims:
        if not isinstance(dim, dict):
            filled.append(dim)
            continue
        row = dict(dim)
        if str(row.get("units") or "").strip():
            filled.append(row)
            continue
        dt = str(row.get("dim_type") or "").strip().upper()
        if "ANGULAR" in dt or dt == "ANGLE":
            row["units"] = angle or "deg"
        elif length:
            row["units"] = length
        filled.append(row)
    snapshot["dimensions"] = filled


def _dimension_outline_line(
    dim: dict[str, Any],
    *,
    feature_labels: dict[str, str] | None = None,
) -> str:
    symbol = str(dim.get("symbol") or "").strip()
    value = _format_dim_value(dim.get("value"))
    unit = str(dim.get("units") or "").strip()
    owner = _dimension_owner_label(dim, feature_labels)
    # Owner name immediately after the dim id: d238 (ROUND) = 1.03 in
    piece = f"{symbol} ({owner}) = {value}" if owner else f"{symbol} = {value}"
    if unit:
        piece += f" {unit}"
    else:
        # Never leave a bare number — Ask AI invents "deg" from neighboring angles.
        dt = str(dim.get("dim_type") or "").strip()
        if dt:
            piece += f" [{dt}]"
        else:
            piece += " [unit unknown]"
    limits = dim.get("tolerance_limits")
    if isinstance(limits, dict) and limits:
        lo = limits.get("lower", limits.get("min"))
        hi = limits.get("upper", limits.get("max"))
        if lo is not None and hi is not None:
            piece += f" (limits {_format_dim_value(lo)}–{_format_dim_value(hi)})"
    return piece


def _dimension_compare_key(dim: dict[str, Any]) -> str:
    """Value+units+limits only (symbol matched separately)."""
    value = _format_dim_value(dim.get("value"))
    unit = str(dim.get("units") or "").strip()
    key = value if not unit else f"{value} {unit}"
    limits = dim.get("tolerance_limits")
    if isinstance(limits, dict) and limits:
        lo = limits.get("lower", limits.get("min"))
        hi = limits.get("upper", limits.get("max"))
        if lo is not None and hi is not None:
            key += f"|{_format_dim_value(lo)}|{_format_dim_value(hi)}"
    return key


def _feature_outline_labels(snapshot: dict[str, Any]) -> list[str]:
    identity = snapshot.get("identity") if isinstance(snapshot.get("identity"), dict) else {}
    drawing = _is_drawing_snapshot(snapshot, identity)
    features_raw = snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
    features = _iter_compare_features(features_raw)
    labels: list[str] = []
    if drawing:
        for feat in features:
            # Drawing dimensions are compared by value in the Dimensions diff, not as labels.
            if not _is_drawing_inventory_compare_feature(feat):
                continue
            if _is_view_feature(feat):
                labels.append(_view_display_line(feat).lstrip("- ").strip())
                continue
            typ = _feature_type_label(feat)
            name = str(feat.get("name") or "").strip() or typ or "item"
            if typ == "NOTE":
                detail = str(feat.get("detail") or "").strip()
                if detail:
                    short = detail if len(detail) <= 40 else detail[:37] + "…"
                    labels.append(f"{name}: {short}")
                    continue
            labels.append(f"{name} ({typ})" if typ and typ not in name.upper() else name)
        return labels
    pattern_i = 0
    for feat in features:
        if _is_pattern_feature(feat):
            pattern_i += 1
            labels.append(_feature_outline_label(feat, pattern_index=pattern_i))
        else:
            labels.append(_feature_outline_label(feat))
    return labels


def _structure_outline_labels(snapshot: dict[str, Any]) -> list[str]:
    return [_structure_compare_label(row) for row in _structure_nodes(snapshot)]


def _simp_reps_dict(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    simp = snapshot.get("simp_reps")
    return simp if isinstance(simp, dict) else None


_CONSTRAINT_OFFSET_EPS = 1e-6


def _constraint_type_allows_offset(type_raw: Any) -> bool:
    """True when Creo UI enables Offset (Mate Offset / Align Offset / dist / angle)."""
    u = str(type_raw or "").upper().replace("PFCCOMPONENTCONSTRAINTTYPE_", "")
    if not u:
        return False
    if "MATE_OFF" in u or "ALIGN_OFF" in u:
        return True
    if "_DIST" in u:
        return True
    if "_ANG" in u or "ANGLE" in u:
        return True
    if "ORIENT" in u:
        return True
    return False


def _constraint_effective_offset(constraint: dict[str, Any]) -> Any:
    """Offset value for compare/outline — null when type has no Offset (API often returns 0)."""
    if not isinstance(constraint, dict):
        return None
    if not _constraint_type_allows_offset(constraint.get("type")):
        return None
    return constraint.get("offset")


def _constraints_dict(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    cons = snapshot.get("constraints")
    return cons if isinstance(cons, dict) else None


def _constraint_occ_components(cons: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(cons, dict):
        return []
    comps = cons.get("components")
    if not isinstance(comps, list):
        return []
    return [c for c in comps if isinstance(c, dict)]


def _constraint_path_key(path: Any) -> str:
    if isinstance(path, list):
        return "/".join(str(x) for x in path)
    if path is None:
        return ""
    return str(path).strip()


def _constraint_occ_key(comp: dict[str, Any]) -> str:
    path = comp.get("component_path")
    if path is None:
        path = comp.get("path")
    cid = comp.get("component_id")
    if cid is None:
        cid = comp.get("id")
    return f"{_constraint_path_key(path)}|{cid}"


def _constraint_occ_display(comp: dict[str, Any]) -> str:
    name = str(comp.get("model_name") or comp.get("name") or "").strip() or "component"
    path = comp.get("component_path")
    if path is None:
        path = comp.get("path")
    path_s = _constraint_path_key(path)
    if path_s:
        return f"{name} ({path_s})"
    cid = comp.get("component_id")
    if cid is None:
        cid = comp.get("id")
    if cid is not None:
        return f"{name} ({cid})"
    return name


def _constraint_type_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "Constraint"
    upper = text.upper()
    for prefix in ("ASM_CONSTRAINT_", "CONSTRAINT_", "PFCCOMPONENTCONSTRAINTTYPE_"):
        if upper.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.replace("_", " ").strip().title() or "Constraint"


def _constraint_ref_key(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    bits = [
        str(ref.get("model") or ""),
        _constraint_path_key(ref.get("component_path")),
        str(ref.get("item_id") if ref.get("item_id") is not None else ""),
        str(ref.get("item_type") or ""),
        str(ref.get("item_name") or ""),
    ]
    return "|".join(bits)


def _constraint_offset_key(constraint: dict[str, Any]) -> str:
    """Null-aware offset key — null is not the same as numeric 0; N/A types → null."""
    offset = _constraint_effective_offset(constraint)
    if offset is None:
        return "null"
    try:
        num = float(offset)
    except (TypeError, ValueError):
        return f"raw:{offset}"
    units = str(constraint.get("offset_units") or "").strip().lower()
    return f"{num:.9g}|{units}"


def _constraint_offsets_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ao = _constraint_effective_offset(a)
    bo = _constraint_effective_offset(b)
    if ao is None and bo is None:
        return True
    if ao is None or bo is None:
        return False
    try:
        an = float(ao)
        bn = float(bo)
    except (TypeError, ValueError):
        return str(ao) == str(bo)
    units_a = str(a.get("offset_units") or "").strip().lower()
    units_b = str(b.get("offset_units") or "").strip().lower()
    if units_a != units_b:
        return False
    return abs(an - bn) <= _CONSTRAINT_OFFSET_EPS


def _constraint_attrs_key(constraint: dict[str, Any]) -> str:
    attrs = constraint.get("attributes")
    if not isinstance(attrs, dict):
        # Legacy flat ignore/force
        ignore = constraint.get("ignore")
        force = constraint.get("force")
        if ignore is None and force is None:
            return ""
        return f"{bool(ignore)}|{bool(force)}"
    return f"{bool(attrs.get('ignore'))}|{bool(attrs.get('force'))}"


def _constraint_fingerprint(constraint: dict[str, Any]) -> str:
    return "|".join(
        [
            str(constraint.get("type") or ""),
            _constraint_offset_key(constraint),
            _constraint_ref_key(constraint.get("assembly_reference") or constraint.get("asm_ref")),
            _constraint_ref_key(constraint.get("component_reference") or constraint.get("comp_ref")),
            str(constraint.get("assembly_datum_side") or ""),
            str(constraint.get("component_datum_side") or ""),
            _constraint_attrs_key(constraint),
        ]
    )


def _constraint_outline_line(constraint: dict[str, Any]) -> str:
    bits = [_constraint_type_label(constraint.get("type"))]
    offset = _constraint_effective_offset(constraint)
    if offset is not None:
        units = str(constraint.get("offset_units") or "").strip()
        try:
            num = float(offset)
            off_s = f"{num:g}"
        except (TypeError, ValueError):
            off_s = str(offset)
        bits.append(f"offset {off_s}" + (f" {units}" if units else ""))
    attrs = constraint.get("attributes")
    if isinstance(attrs, dict):
        if attrs.get("ignore"):
            bits.append("ignore")
        if attrs.get("force"):
            bits.append("force")
    elif constraint.get("ignore"):
        bits.append("ignore")
    return " · ".join(bits)


def _constraint_occ_outline_line(comp: dict[str, Any]) -> str:
    head = _constraint_occ_display(comp)
    status = str(comp.get("capture_status") or "").strip().lower()
    if status and status not in ("ok",):
        err = str(comp.get("error") or "").strip()
        return f"{head}: capture {status}" + (f" ({err})" if err else "")
    placement = comp.get("placement") if isinstance(comp.get("placement"), dict) else {}
    place_bits: list[str] = []
    if placement.get("packaged") is True:
        place_bits.append("packaged")
    if placement.get("underconstrained") is True:
        place_bits.append("underconstrained")
    if placement.get("frozen") is True:
        place_bits.append("frozen")
    if placement.get("placed") is False:
        place_bits.append("not placed")
    constraints = comp.get("constraints")
    if not isinstance(constraints, list):
        constraints = []
    cons_bits = [_constraint_outline_line(c) for c in constraints if isinstance(c, dict)]
    tail_bits = place_bits + cons_bits
    if not tail_bits:
        return f"{head}: (no constraints)"
    return f"{head}: " + "; ".join(tail_bits)


def _constraints_outline_lines(snapshot: dict[str, Any]) -> list[str]:
    cons = _constraints_dict(snapshot)
    if not cons:
        return []
    comps = _constraint_occ_components(cons)
    lines = ["Assembly constraints:"]
    if not comps:
        lines.append("- (none)")
        return lines
    for comp in comps:
        lines.append(f"- {_constraint_occ_outline_line(comp)}")
    return lines


def _constraint_field_deltas(
    older_c: dict[str, Any], newer_c: dict[str, Any]
) -> list[str]:
    """Return human single-field change phrases when exactly one semantic field differs."""
    deltas: list[str] = []
    if str(older_c.get("type") or "") != str(newer_c.get("type") or ""):
        deltas.append(
            f"type {_constraint_type_label(older_c.get('type'))} → "
            f"{_constraint_type_label(newer_c.get('type'))}"
        )
    if not _constraint_offsets_equal(older_c, newer_c):
        def _off_label(c: dict[str, Any]) -> str:
            off = _constraint_effective_offset(c)
            if off is None:
                return "(null)"
            units = str(c.get("offset_units") or "").strip()
            try:
                num = float(off)
                text = f"{num:g}"
            except (TypeError, ValueError):
                text = str(off)
            return f"{text} {units}".strip()

        deltas.append(f"offset {_off_label(older_c)} → {_off_label(newer_c)}")
    if _constraint_ref_key(
        older_c.get("assembly_reference") or older_c.get("asm_ref")
    ) != _constraint_ref_key(
        newer_c.get("assembly_reference") or newer_c.get("asm_ref")
    ):
        deltas.append("assembly reference changed")
    if _constraint_ref_key(
        older_c.get("component_reference") or older_c.get("comp_ref")
    ) != _constraint_ref_key(
        newer_c.get("component_reference") or newer_c.get("comp_ref")
    ):
        deltas.append("component reference changed")
    if str(older_c.get("assembly_datum_side") or "") != str(
        newer_c.get("assembly_datum_side") or ""
    ) or str(older_c.get("component_datum_side") or "") != str(
        newer_c.get("component_datum_side") or ""
    ):
        deltas.append("datum side changed")
    if _constraint_attrs_key(older_c) != _constraint_attrs_key(newer_c):
        deltas.append("ignore/force changed")
    return deltas


def _diff_constraint_lists(
    older_list: list[dict[str, Any]], newer_list: list[dict[str, Any]]
) -> tuple[list[str], list[str], list[str]]:
    """Multiset match constraints; return (removed, added, changed) display lines."""
    older_fp = [_constraint_fingerprint(c) for c in older_list]
    newer_fp = [_constraint_fingerprint(c) for c in newer_list]
    older_counts = Counter(older_fp)
    newer_counts = Counter(newer_fp)
    # Perfect multiset equality → no per-constraint noise (reorder-only).
    if older_counts == newer_counts:
        return [], [], []

    remaining_old = list(older_list)
    remaining_new = list(newer_list)
    removed: list[str] = []
    added: list[str] = []
    changed: list[str] = []

    # Exact fingerprint matches consume pairs.
    used_new: set[int] = set()
    kept_old: list[dict[str, Any]] = []
    for oc in remaining_old:
        fp = _constraint_fingerprint(oc)
        matched = False
        for ni, nc in enumerate(remaining_new):
            if ni in used_new:
                continue
            if _constraint_fingerprint(nc) == fp:
                used_new.add(ni)
                matched = True
                break
        if not matched:
            kept_old.append(oc)
    kept_new = [nc for ni, nc in enumerate(remaining_new) if ni not in used_new]

    # Pair unambiguous single-field deltas by type.
    still_old = list(kept_old)
    still_new = list(kept_new)
    paired_old: set[int] = set()
    paired_new: set[int] = set()
    for oi, oc in enumerate(still_old):
        candidates: list[tuple[int, list[str]]] = []
        for ni, nc in enumerate(still_new):
            if ni in paired_new:
                continue
            deltas = _constraint_field_deltas(oc, nc)
            if len(deltas) == 1:
                candidates.append((ni, deltas))
        if len(candidates) == 1:
            ni, deltas = candidates[0]
            # Ensure only one old maps to this new
            reverse = [
                oj
                for oj, o2 in enumerate(still_old)
                if oj not in paired_old
                and len(_constraint_field_deltas(o2, still_new[ni])) == 1
            ]
            if reverse == [oi]:
                paired_old.add(oi)
                paired_new.add(ni)
                changed.append(deltas[0])
    for oi, oc in enumerate(still_old):
        if oi not in paired_old:
            removed.append(_constraint_outline_line(oc))
    for ni, nc in enumerate(still_new):
        if ni not in paired_new:
            added.append(_constraint_outline_line(nc))
    return removed, added, changed


def _constraints_diff_lines(
    older: dict[str, Any], newer: dict[str, Any]
) -> list[str]:
    """Authoritative assembly constraint diffs — missing envelope → Not captured."""
    older_cons = _constraints_dict(older)
    newer_cons = _constraints_dict(newer)
    if older_cons is None and newer_cons is None:
        return []
    if older_cons is None or newer_cons is None:
        return [
            "Assembly constraints: Not captured on one revision "
            "(not treated as removals or adds)."
        ]

    older_by = {_constraint_occ_key(c): c for c in _constraint_occ_components(older_cons)}
    newer_by = {_constraint_occ_key(c): c for c in _constraint_occ_components(newer_cons)}
    keys = sorted(set(older_by) | set(newer_by), key=str.lower)
    lines: list[str] = []

    def _extend_block(block: list[str]) -> None:
        if not block:
            return
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(block)

    for key in keys:
        old_c = older_by.get(key)
        new_c = newer_by.get(key)
        label = _constraint_occ_display(new_c or old_c or {})
        if old_c is None and new_c is not None:
            cons = new_c.get("constraints") if isinstance(new_c.get("constraints"), list) else []
            bits = [_constraint_outline_line(c) for c in cons if isinstance(c, dict)]
            add_block = [f"Assembly constraints added ({label}):"]
            add_block.extend([f"- {b}" for b in bits] if bits else ["- (occurrence added)"])
            _extend_block(add_block)
            continue
        if old_c is not None and new_c is None:
            cons = old_c.get("constraints") if isinstance(old_c.get("constraints"), list) else []
            bits = [_constraint_outline_line(c) for c in cons if isinstance(c, dict)]
            rem_block = [f"Assembly constraints removed ({label}):"]
            rem_block.extend(
                [f"- {b}" for b in bits] if bits else ["- (occurrence removed)"]
            )
            _extend_block(rem_block)
            continue
        assert old_c is not None and new_c is not None
        # Placement flag changes
        old_p = old_c.get("placement") if isinstance(old_c.get("placement"), dict) else {}
        new_p = new_c.get("placement") if isinstance(new_c.get("placement"), dict) else {}
        place_changes: list[str] = []
        for flag in ("placed", "packaged", "underconstrained", "frozen"):
            if old_p.get(flag) != new_p.get(flag) and (
                old_p.get(flag) is not None or new_p.get(flag) is not None
            ):
                place_changes.append(f"{flag}: {old_p.get(flag)} → {new_p.get(flag)}")
        old_list = [
            c for c in (old_c.get("constraints") or []) if isinstance(c, dict)
        ] if isinstance(old_c.get("constraints"), list) else []
        new_list = [
            c for c in (new_c.get("constraints") or []) if isinstance(c, dict)
        ] if isinstance(new_c.get("constraints"), list) else []
        # Unavailable vs ok — surface status, do not invent mass removals from null.
        old_status = str(old_c.get("capture_status") or "ok")
        new_status = str(new_c.get("capture_status") or "ok")
        if old_status != new_status and (
            old_c.get("constraints") is None or new_c.get("constraints") is None
        ):
            _extend_block(
                [
                    f"Assembly constraints capture status ({label}):",
                    f"- {old_status} → {new_status}",
                ]
            )
            if place_changes:
                _extend_block(
                    [
                        f"Assembly placement changed ({label}):",
                        *[f"- {p}" for p in place_changes],
                    ]
                )
            continue
        removed, added, changed = _diff_constraint_lists(old_list, new_list)
        if place_changes:
            _extend_block(
                [
                    f"Assembly placement changed ({label}):",
                    *[f"- {p}" for p in place_changes],
                ]
            )
        if removed:
            _extend_block(
                [
                    f"Assembly constraints removed ({label}):",
                    *[f"- {r}" for r in removed],
                ]
            )
        if added:
            _extend_block(
                [
                    f"Assembly constraints added ({label}):",
                    *[f"- {a}" for a in added],
                ]
            )
        if changed:
            _extend_block(
                [
                    f"Assembly constraints changed ({label}):",
                    *[f"- {c}" for c in changed],
                ]
            )
    return lines


def _relations_dict(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    rel = snapshot.get("relations")
    return rel if isinstance(rel, dict) else None


def _relation_trim_lines(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if text:
            out.append(text)
    return out


def _relation_line_multiset_delta(
    older_lines: list[str], newer_lines: list[str]
) -> tuple[list[str], list[str]]:
    """Return (removed, added); reorder-only → empty. Preserves duplicates."""
    older_counts = Counter(older_lines)
    newer_counts = Counter(newer_lines)
    if older_counts == newer_counts:
        return [], []
    removed: list[str] = []
    added: list[str] = []
    for line in sorted(set(older_counts) | set(newer_counts), key=str.lower):
        delta = newer_counts.get(line, 0) - older_counts.get(line, 0)
        if delta < 0:
            removed.extend([line] * (-delta))
        elif delta > 0:
            added.extend([line] * delta)
    return removed, added


def _relations_outline_lines(snapshot: dict[str, Any]) -> list[str]:
    rel = _relations_dict(snapshot)
    if not rel:
        return []
    lines: list[str] = []
    normal = _relation_trim_lines(rel.get("normal"))
    post = _relation_trim_lines(rel.get("post_regeneration"))
    feat_rows = rel.get("features") if isinstance(rel.get("features"), list) else []
    feat_rows = [f for f in feat_rows if isinstance(f, dict)]

    # Always outline when envelope present (even all-empty) so Diff can mark first capture.
    lines.append("Relations:")
    if normal:
        lines.extend([f"- {b}" for b in normal])
    else:
        lines.append("- (none)")
    if post:
        lines.append("")
        lines.append("Post-regeneration relations:")
        lines.extend([f"- {b}" for b in post])
    if feat_rows:
        lines.append("")
        lines.append("Feature relations:")
        for feat in feat_rows:
            fid = feat.get("feature_id")
            name = str(feat.get("feature_name") or "").strip() or "feature"
            head = f"{name} ({fid})" if fid is not None else name
            feat_lines = _relation_trim_lines(feat.get("relations"))
            if not feat_lines:
                lines.append(f"- {head}: (none)")
            else:
                lines.append(f"- {head}:")
                for fl in feat_lines:
                    lines.append(f"  - {fl}")
    return lines


def _relations_diff_lines(
    older: dict[str, Any], newer: dict[str, Any]
) -> list[str]:
    """Authoritative relation line diffs — missing envelope → Not captured."""
    older_rel = _relations_dict(older)
    newer_rel = _relations_dict(newer)
    if older_rel is None and newer_rel is None:
        return []
    if older_rel is None or newer_rel is None:
        return [
            "Relations: Not captured on one revision "
            "(not treated as removals or adds)."
        ]

    lines: list[str] = []

    def _extend_block(block: list[str]) -> None:
        if not block:
            return
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(block)

    for title, key in (
        ("Relations", "normal"),
        ("Post-regeneration relations", "post_regeneration"),
    ):
        old_lines = _relation_trim_lines(older_rel.get(key))
        new_lines = _relation_trim_lines(newer_rel.get(key))
        removed, added = _relation_line_multiset_delta(old_lines, new_lines)
        if removed:
            _extend_block([f"{title} removed:", *[f"- {r}" for r in removed]])
        if added:
            _extend_block([f"{title} added:", *[f"- {a}" for a in added]])

    older_feats = {
        str(f.get("feature_id")): f
        for f in (older_rel.get("features") or [])
        if isinstance(f, dict) and f.get("feature_id") is not None
    }
    newer_feats = {
        str(f.get("feature_id")): f
        for f in (newer_rel.get("features") or [])
        if isinstance(f, dict) and f.get("feature_id") is not None
    }
    for key in sorted(set(older_feats) | set(newer_feats), key=str.lower):
        old_f = older_feats.get(key)
        new_f = newer_feats.get(key)
        label_src = new_f or old_f or {}
        name = str(label_src.get("feature_name") or "").strip() or "feature"
        label = f"{name} ({label_src.get('feature_id')})"
        old_lines = _relation_trim_lines(old_f.get("relations") if old_f else [])
        new_lines = _relation_trim_lines(new_f.get("relations") if new_f else [])
        removed, added = _relation_line_multiset_delta(old_lines, new_lines)
        if removed:
            _extend_block(
                [f"Feature relations removed ({label}):", *[f"- {r}" for r in removed]]
            )
        if added:
            _extend_block(
                [f"Feature relations added ({label}):", *[f"- {a}" for a in added]]
            )
    return lines


def _simp_rep_active_name(simp: dict[str, Any] | None) -> str:
    if not isinstance(simp, dict):
        return ""
    active = simp.get("active")
    if not isinstance(active, dict):
        return ""
    name = str(active.get("name") or "").strip()
    if name:
        return name
    return "MASTER" if active.get("is_master") else ""


def _simp_rep_names(simp: dict[str, Any] | None) -> list[str]:
    """Named saved representation names only (order preserved, no rule noise)."""
    if not isinstance(simp, dict):
        return []
    reps = simp.get("representations")
    if not isinstance(reps, list):
        return []
    names: list[str] = []
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        name = str(rep.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _simp_rep_named_labels(simp: dict[str, Any] | None) -> list[str]:
    """Stable labels for named saved representations (definitions, not Structure)."""
    if not isinstance(simp, dict):
        return []
    reps = simp.get("representations")
    if not isinstance(reps, list):
        return []
    labels: list[str] = []
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        name = str(rep.get("name") or "").strip()
        if not name:
            continue
        bits = [name]
        default = str(rep.get("default_action") or "").strip()
        if default:
            bits.append(f"default {default}")
        items = rep.get("items")
        n_items = len(items) if isinstance(items, list) else 0
        if n_items:
            bits.append(f"{n_items} item rule(s)")
        labels.append(" · ".join(bits))
    return labels


def _english_name_list(names: list[str]) -> str:
    clean = [n for n in names if n]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def _simp_reps_diff_lines(
    older: dict[str, Any], newer: dict[str, Any]
) -> list[str]:
    """Authoritative SimpRep definition/active diffs for Computed differences."""
    older_simp = _simp_reps_dict(older)
    newer_simp = _simp_reps_dict(newer)
    older_names = _simp_rep_names(older_simp)
    newer_names = _simp_rep_names(newer_simp)
    older_labels = _simp_rep_named_labels(older_simp)
    newer_labels = _simp_rep_named_labels(newer_simp)
    older_has = bool(older_names) or bool(_simp_rep_active_name(older_simp))
    newer_has = bool(newer_names) or bool(_simp_rep_active_name(newer_simp))
    if not older_has and not newer_has:
        return []

    lines: list[str] = []
    older_active = _simp_rep_active_name(older_simp)
    newer_active = _simp_rep_active_name(newer_simp)

    def _bullet_names(title: str, names: list[str]) -> list[str]:
        # Same shape as Components/Features — readable in What changed + Ask AI.
        if not names:
            return [f"{title}: (none)"]
        return [f"{title}:", *[f"- {name}" for name in names]]

    def _extend_block(block: list[str]) -> None:
        if not block:
            return
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(block)

    if not older_has and newer_has:
        return _bullet_names("Simplified representations added", newer_names)

    if older_has and not newer_has:
        return _bullet_names("Simplified representations removed", older_names)

    if older_active and newer_active and older_active != newer_active:
        _extend_block(
            [
                "Active simplified representation changed:",
                f"- {older_active} → {newer_active}",
            ]
        )

    older_counts = _count_labels(older_labels)
    newer_counts = _count_labels(newer_labels)
    removed: list[str] = []
    added: list[str] = []
    for label in sorted(set(older_counts) | set(newer_counts), key=str.lower):
        delta = newer_counts.get(label, 0) - older_counts.get(label, 0)
        if delta < 0:
            removed.extend([label] * (-delta))
        elif delta > 0:
            added.extend([label] * delta)
    # Prefer name-only when whole named reps appeared/disappeared.
    older_name_counts = _count_labels(older_names)
    newer_name_counts = _count_labels(newer_names)
    names_removed = [
        n
        for n in sorted(set(older_name_counts) | set(newer_name_counts), key=str.lower)
        if newer_name_counts.get(n, 0) < older_name_counts.get(n, 0)
        for _ in range(older_name_counts.get(n, 0) - newer_name_counts.get(n, 0))
    ]
    names_added = [
        n
        for n in sorted(set(older_name_counts) | set(newer_name_counts), key=str.lower)
        if newer_name_counts.get(n, 0) > older_name_counts.get(n, 0)
        for _ in range(newer_name_counts.get(n, 0) - older_name_counts.get(n, 0))
    ]
    if names_removed:
        _extend_block(_bullet_names("Simplified representations removed", names_removed))
    if names_added:
        _extend_block(_bullet_names("Simplified representations added", names_added))
    # Same names but rule/default text changed — only then show detail labels.
    if not names_removed and not names_added and (removed or added):
        if removed:
            _extend_block(
                [
                    "Simplified representation rules changed (removed):",
                    *[f"- {item}" for item in removed],
                ]
            )
        if added:
            _extend_block(
                [
                    "Simplified representation rules changed (added):",
                    *[f"- {item}" for item in added],
                ]
            )
    return lines

def _simp_reps_outline_lines(snapshot: dict[str, Any]) -> list[str]:
    """Assembly simplified representation definitions (not BOM membership)."""
    simp = _simp_reps_dict(snapshot)
    if not simp:
        return []
    reps = simp.get("representations")
    if not isinstance(reps, list) or not reps:
        # Still surface active Master / named context when defs empty.
        active = simp.get("active") if isinstance(simp.get("active"), dict) else None
        if not active:
            return []
        name = str(active.get("name") or "").strip() or (
            "MASTER" if active.get("is_master") else "—"
        )
        return [f"Simplified representations (active: {name}):", "- (none listed)"]
    lines: list[str] = []
    active = simp.get("active") if isinstance(simp.get("active"), dict) else None
    active_name = ""
    if active:
        active_name = str(active.get("name") or "").strip() or (
            "MASTER" if active.get("is_master") else ""
        )
    header = "Simplified representations:"
    if active_name:
        header = f"Simplified representations (active: {active_name}):"
    lines.append(header)
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        name = str(rep.get("name") or "").strip() or "—"
        bits = [name]
        typ = str(rep.get("type") or "").strip()
        if typ:
            bits.append(typ)
        default = str(rep.get("default_action") or "").strip()
        if default:
            bits.append(f"default {default}")
        if rep.get("temporary") is True:
            bits.append("temporary")
        items = rep.get("items")
        n_items = len(items) if isinstance(items, list) else 0
        if n_items:
            bits.append(f"{n_items} item rule(s)")
        elif rep.get("instructions_available") is False:
            bits.append("instructions unavailable")
        lines.append("- " + " · ".join(bits))
    return lines

def _count_labels(labels: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return counts


def snapshot_compare_diff_is_empty(diff_text: str) -> bool:
    """True when Computed differences has only the banner and ``(none)`` rows.

    Matches Modifications UI ``formatAiWhatChangedDisplay`` →
    ``No computed differences.`` Ask AI must not call Ollama in that case.
    """
    for raw in str(diff_text or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        if re.match(r"^=== Computed differences ===$", text, re.IGNORECASE):
            continue
        if re.search(r":\s*\(none\)\s*$", text, re.IGNORECASE):
            continue
        return False
    return True


def empty_snapshot_compare_summary(
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """One-line Ask AI / check-in comment when Computed differences are empty."""
    older_label = (older_revision or "").strip()
    newer_label = (newer_revision or "").strip()
    if not older_label or older_label in {"—", "-"}:
        older_label = "older"
    if not newer_label or newer_label in {"—", "-"}:
        newer_label = "newer"
    return f"Nothing changed between {older_label} and {newer_label}."


def _feature_compare_key(feat: dict[str, Any]) -> str | None:
    """Same feature in two snapshots: the Creo id, else the (lower-cased) name."""
    fid = _norm_feature_id(feat.get("id"))
    if fid:
        return f"id:{fid}"
    name = str(feat.get("name") or "").strip().lower()
    return f"name:{name}" if name else None


def _by_insert_mode(feat: dict[str, Any]) -> bool:
    """Rows with ``after_insert`` are suppressed by Insert mode, not by the user."""
    return bool(feat.get("after_insert"))


def _feature_user_state(feat: dict[str, Any]) -> str:
    """'suppressed' (the user did it), 'active', or the Creo status text.

    A row that Insert mode suppresses (``after_insert``) is NOT user-suppressed: its
    suppressed flag / SUPPRESSED status come from the insert point and are reported by the
    Insert mode block instead.
    """
    status = str(feat.get("status") or "").strip().upper()
    suppressed = bool(feat.get("suppressed")) or "SUPPRESS" in status
    if _by_insert_mode(feat):
        suppressed = False
        if "SUPPRESS" in status:
            status = ""
    if suppressed:
        return "suppressed"
    if status in {"", "ACTIVE", "NORMAL"} or status.startswith("SIMP_REP"):
        return "active"
    return status.lower()


def _compare_feature_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Features of a PART / ASSEMBLY snapshot as the compare sees them (none for a drawing)."""
    identity = snapshot.get("identity") if isinstance(snapshot.get("identity"), dict) else {}
    if _is_drawing_snapshot(snapshot, identity):
        return []
    raw = snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
    return _iter_compare_features(raw)


def _feature_state_diff_lines(older: dict[str, Any], newer: dict[str, Any]) -> list[str]:
    """Features present in both whose status / suppressed state changed (user suppress, resume …)."""
    old_rows = {}
    for feat in _compare_feature_rows(older):
        key = _feature_compare_key(feat)
        if key and key not in old_rows:
            old_rows[key] = feat
    changed: list[str] = []
    seen: set[str] = set()
    for feat in _compare_feature_rows(newer):
        key = _feature_compare_key(feat)
        if not key or key in seen or key not in old_rows:
            continue
        seen.add(key)
        before = _feature_user_state(old_rows[key])
        after = _feature_user_state(feat)
        if before != after:
            changed.append(f"{_feature_outline_label(feat)}: {before} → {after}")
    return ["Features status changed:", *[f"- {item}" for item in changed]] if changed else []


def _insert_mode(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """``domains.features.insert_mode`` as kept in the snapshot: active, after_feature_id/name."""
    raw = snapshot.get("insert_mode")
    if not isinstance(raw, dict):
        return None
    active = bool(raw.get("active"))
    return {
        "active": active,
        "after_id": _norm_feature_id(raw.get("after_feature_id")) if active else None,
        "after_name": str(raw.get("after_feature_name") or "").strip() if active else "",
    }


def _insert_after_label(mode: dict[str, Any], snapshot: dict[str, Any]) -> str:
    name = str(mode.get("after_name") or "").strip()
    fid = mode.get("after_id")
    if not name and fid:
        name = _feature_id_label_map(snapshot).get(str(fid), "") or f"feature {fid}"
    if name and fid and f"({fid})" not in name:
        return f"{name} ({fid})"
    return name or "(unknown feature)"


def _insert_mode_diff_lines(older: dict[str, Any], newer: dict[str, Any]) -> list[str]:
    """Insert mode turned on / off / moved, and the features that became suppressed by it."""
    old_mode = _insert_mode(older) or {"active": False, "after_id": None, "after_name": ""}
    new_mode = _insert_mode(newer) or {"active": False, "after_id": None, "after_name": ""}
    if old_mode["active"] and new_mode["active"]:
        moved = (old_mode["after_id"], old_mode["after_name"].lower()) != (
            new_mode["after_id"],
            new_mode["after_name"].lower(),
        )
        if not moved:
            return []
        head = (
            f"Insert mode moved: after {_insert_after_label(new_mode, newer)}"
            f" (was after {_insert_after_label(old_mode, older)})"
        )
    elif new_mode["active"]:
        head = f"Insert mode on: after {_insert_after_label(new_mode, newer)}"
    elif old_mode["active"]:
        head = f"Insert mode off (was after {_insert_after_label(old_mode, older)})"
    else:
        return []
    old_by_insert = {
        key
        for feat in _compare_feature_rows(older)
        if _by_insert_mode(feat) and (key := _feature_compare_key(feat))
    }
    became: list[str] = []
    seen: set[str] = set()
    for feat in _compare_feature_rows(newer):
        key = _feature_compare_key(feat)
        if not key or key in seen or not _by_insert_mode(feat) or key in old_by_insert:
            continue
        seen.add(key)
        became.append(_feature_outline_label(feat))
    lines = ["Insert mode:", f"- {head}"]
    if became:
        # The count is printed, so a model reading this never has to count a long list itself.
        lines += [
            f"Features suppressed by insert mode ({len(became)}):",
            *[f"- {item}" for item in became],
        ]
    return lines


def format_snapshot_compare_diff_text(
    older_snapshot: dict[str, Any] | None,
    newer_snapshot: dict[str, Any] | None,
) -> str:
    """Authoritative OLD→NEW feature/dimension/BOM diffs (prevents cross-symbol dim merges)."""
    older = older_snapshot if isinstance(older_snapshot, dict) else {}
    newer = newer_snapshot if isinstance(newer_snapshot, dict) else {}

    older_feats = _count_labels(_feature_outline_labels(older))
    newer_feats = _count_labels(_feature_outline_labels(newer))
    feat_removed: list[str] = []
    feat_added: list[str] = []
    for label in sorted(set(older_feats) | set(newer_feats), key=str.lower):
        delta = newer_feats.get(label, 0) - older_feats.get(label, 0)
        if delta < 0:
            feat_removed.extend([label] * (-delta))
        elif delta > 0:
            feat_added.extend([label] * delta)

    older_comps = _bom_member_qty_map(_bom_nodes(older))
    newer_comps = _bom_member_qty_map(_bom_nodes(newer))
    comp_removed: list[str] = []
    comp_added: list[str] = []
    comp_qty_changed: list[str] = []
    for key in sorted(set(older_comps) | set(newer_comps), key=str.lower):
        old_entry = older_comps.get(key)
        new_entry = newer_comps.get(key)
        if old_entry is not None and new_entry is None:
            comp_removed.append(_component_outline_label(old_entry[0], old_entry[1]))
        elif old_entry is None and new_entry is not None:
            comp_added.append(_component_outline_label(new_entry[0], new_entry[1]))
        elif old_entry is not None and new_entry is not None:
            old_qty, new_qty = old_entry[1], new_entry[1]
            if old_qty != new_qty:
                display = new_entry[0] or old_entry[0]
                comp_qty_changed.append(f"{display}: × {old_qty} → × {new_qty}")

    # When BOM is absent, compare assembly inventory structure labels.
    if not older_comps and not newer_comps:
        older_struct = _count_labels(_structure_outline_labels(older))
        newer_struct = _count_labels(_structure_outline_labels(newer))
        for label in sorted(set(older_struct) | set(newer_struct), key=str.lower):
            delta = newer_struct.get(label, 0) - older_struct.get(label, 0)
            if delta < 0:
                comp_removed.extend([label] * (-delta))
            elif delta > 0:
                comp_added.extend([label] * delta)

    older_feat_labels = _feature_id_label_map(older)
    newer_feat_labels = _feature_id_label_map(newer)
    older_dims = {
        str(d.get("symbol") or "").strip(): d
        for d in _compare_dimension_rows(older)
        if str(d.get("symbol") or "").strip()
    }
    newer_dims = {
        str(d.get("symbol") or "").strip(): d
        for d in _compare_dimension_rows(newer)
        if str(d.get("symbol") or "").strip()
    }
    dim_removed: list[str] = []
    dim_added: list[str] = []
    dim_changed: list[str] = []
    for symbol in sorted(set(older_dims) | set(newer_dims), key=str.lower):
        old_dim = older_dims.get(symbol)
        new_dim = newer_dims.get(symbol)
        if old_dim is not None and new_dim is None:
            dim_removed.append(
                _dimension_outline_line(old_dim, feature_labels=older_feat_labels)
            )
        elif old_dim is None and new_dim is not None:
            dim_added.append(
                _dimension_outline_line(new_dim, feature_labels=newer_feat_labels)
            )
        elif old_dim is not None and new_dim is not None:
            if _dimension_compare_key(old_dim) != _dimension_compare_key(new_dim):
                dim_changed.append(
                    f"{symbol}: "
                    f"{_dimension_outline_line(old_dim, feature_labels=older_feat_labels).split(' = ', 1)[-1]} → "
                    f"{_dimension_outline_line(new_dim, feature_labels=newer_feat_labels).split(' = ', 1)[-1]}"
                )

    def _bullet_block(title: str, items: list[str]) -> list[str]:
        if not items:
            return [f"{title}: (none)"]
        return [f"{title}:", *[f"- {item}" for item in items]]

    def _extend_section(dest: list[str], block: list[str]) -> None:
        """Blank line between major sections (Components / Dimensions / SimpRep)."""
        if not block:
            return
        if dest and dest[-1] != "" and dest[-1] != "=== Computed differences ===":
            dest.append("")
        dest.extend(block)

    # Both sides have Structure (BOM or inventory) → BOM/structure is
    # authoritative for assemblies. Pending Check In gathers often differ on
    # non-component features (ACS*/datums) even when Structure is unchanged.
    older_has_struct = bool(older_comps) or bool(_structure_nodes(older))
    newer_has_struct = bool(newer_comps) or bool(_structure_nodes(newer))
    both_have_structure = older_has_struct and newer_has_struct
    has_structure = older_has_struct or newer_has_struct
    if both_have_structure:
        feat_removed = []
        feat_added = []

    # Diff facts only — narrative instructions live in System Settings → AI prompt.
    lines = ["=== Computed differences ==="]
    if has_structure:
        _extend_section(lines, _bullet_block("Components removed", comp_removed))
        _extend_section(lines, _bullet_block("Components added", comp_added))
        _extend_section(lines, _bullet_block("Components quantity changed", comp_qty_changed))
    for title, items in (
        ("Features removed", feat_removed),
        ("Features added", feat_added),
    ):
        _extend_section(lines, _bullet_block(title, items))
    # Status / suppressed per feature and Insert mode apply to parts AND assemblies, also when
    # the Structure is the authority for what was added or removed (above).
    for block in (_insert_mode_diff_lines(older, newer), _feature_state_diff_lines(older, newer)):
        if block:
            _extend_section(lines, block)
    for title, items in (
        ("Dimensions removed", dim_removed),
        ("Dimensions changed (same symbol)", dim_changed),
        ("Dimensions added", dim_added),
    ):
        _extend_section(lines, _bullet_block(title, items))

    # Parameters / material — shown in OLD/NEW outlines but were missing from
    # Computed differences (DESIGNATION-only edits looked like "No computed differences").
    older_drawing = _is_drawing_snapshot(
        older, older.get("identity") if isinstance(older.get("identity"), dict) else {}
    )
    newer_drawing = _is_drawing_snapshot(
        newer, newer.get("identity") if isinstance(newer.get("identity"), dict) else {}
    )
    older_params = {
        str(p.get("name") or "").strip().upper(): p
        for p in _iter_compare_parameters(
            older.get("parameters") if isinstance(older.get("parameters"), list) else [],
            drawing=older_drawing,
        )
        if str(p.get("name") or "").strip()
    }
    newer_params = {
        str(p.get("name") or "").strip().upper(): p
        for p in _iter_compare_parameters(
            newer.get("parameters") if isinstance(newer.get("parameters"), list) else [],
            drawing=newer_drawing,
        )
        if str(p.get("name") or "").strip()
    }
    param_removed: list[str] = []
    param_added: list[str] = []
    param_changed: list[str] = []
    for key in sorted(set(older_params) | set(newer_params), key=str.lower):
        old_p = older_params.get(key)
        new_p = newer_params.get(key)
        if old_p is not None and new_p is None:
            param_removed.append(_parameter_outline_line(old_p))
        elif old_p is None and new_p is not None:
            param_added.append(_parameter_outline_line(new_p))
        elif old_p is not None and new_p is not None:
            old_v = _parameter_value_str(old_p)
            new_v = _parameter_value_str(new_p)
            if old_v != new_v:
                name = str(new_p.get("name") or old_p.get("name") or key).strip()
                param_changed.append(f"{name}: {old_v} → {new_v}")

    older_mat = _material_current_label(older)
    newer_mat = _material_current_label(newer)
    if older_mat != newer_mat and (older_mat or newer_mat):
        _extend_section(
            lines,
            [
                "Material changed:",
                f"- {older_mat or '(none)'} → {newer_mat or '(none)'}",
            ],
        )
    for title, items in (
        ("Parameters removed", param_removed),
        ("Parameters changed (same name)", param_changed),
        ("Parameters added", param_added),
    ):
        _extend_section(lines, _bullet_block(title, items))

    mass_diff = _mass_diff_lines(older, newer)
    if mass_diff:
        _extend_section(lines, mass_diff)

    # SimpRep defs/active — keep out of Structure; force into Computed differences
    # so Ask AI cannot miss "NEW has Simplified representations, OLD does not."
    simp_diff = _simp_reps_diff_lines(older, newer)
    if simp_diff:
        _extend_section(lines, simp_diff)
    cons_diff = _constraints_diff_lines(older, newer)
    if cons_diff:
        _extend_section(lines, cons_diff)
    rel_diff = _relations_diff_lines(older, newer)
    if rel_diff:
        _extend_section(lines, rel_diff)
    return "\n".join(lines)


def _parameter_value_str(param: dict[str, Any]) -> str:
    value = param.get("value")
    if isinstance(value, str):
        return value.strip()
    return _format_dim_value(value)


def _parameter_outline_line(param: dict[str, Any]) -> str:
    name = str(param.get("name") or "").strip() or "?"
    return f"{name} = {_parameter_value_str(param)}"


def _material_current_label(snapshot: dict[str, Any]) -> str:
    materials = snapshot.get("materials")
    if not isinstance(materials, dict):
        return ""
    current = str(materials.get("current") or "").strip()
    if current:
        return current
    names = [
        str(n).strip() for n in (materials.get("names") or []) if str(n).strip()
    ]
    if len(names) == 1:
        return names[0]
    if names:
        return ", ".join(names)
    return ""


_MASS_COMPARE_KEYS = (
    "mass",
    "volume",
    "density",
    "surface_area",
    "gravity_center",
    "principal_moments",
)


def _mass_props(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    mass = snapshot.get("mass")
    if not isinstance(mass, dict):
        return None
    out = {k: mass[k] for k in _MASS_COMPARE_KEYS if k in mass and mass[k] is not None}
    return out or None


def _format_mass_scalar(value: Any) -> str:
    """6 significant digits, the same text the Details Mass tab shows (shared formatter)."""
    return format_mass_value(value)


def _mass_outline_lines(snapshot: dict[str, Any]) -> list[str]:
    props = _mass_props(snapshot)
    if not props:
        return []
    units = snapshot.get("units") if isinstance(snapshot.get("units"), dict) else {}
    mass_unit = str((units or {}).get("mass") or "").strip()
    lines = ["Mass properties:"]
    for key in _MASS_COMPARE_KEYS:
        if key not in props:
            continue
        label = key.replace("_", " ")
        text = _format_mass_scalar(props[key])
        if key == "mass" and mass_unit:
            text = f"{text} {mass_unit}"
        lines.append(f"- {label}: {text}")
    return lines


def _mass_compare_key(props: dict[str, Any] | None) -> str:
    if not props:
        return ""
    bits: list[str] = []
    for key in _MASS_COMPARE_KEYS:
        if key not in props:
            continue
        bits.append(f"{key}={_format_mass_scalar(props[key])}")
    return "|".join(bits)


def _mass_diff_lines(
    older: dict[str, Any],
    newer: dict[str, Any],
) -> list[str]:
    """Mass in Computed differences when either side captured properties."""
    old_props = _mass_props(older)
    new_props = _mass_props(newer)
    if not old_props and not new_props:
        return []
    if _mass_compare_key(old_props) == _mass_compare_key(new_props):
        return []
    if not old_props:
        assert new_props is not None
        return [
            "Mass properties changed:",
            "- (not captured) → " + "; ".join(
                f"{k.replace('_', ' ')} {_format_mass_scalar(v)}"
                for k, v in new_props.items()
            ),
        ]
    if not new_props:
        return [
            "Mass properties changed:",
            "- "
            + "; ".join(
                f"{k.replace('_', ' ')} {_format_mass_scalar(v)}"
                for k, v in old_props.items()
            )
            + " → (not captured)",
        ]
    changed: list[str] = []
    for key in _MASS_COMPARE_KEYS:
        ov = old_props.get(key)
        nv = new_props.get(key)
        if ov is None and nv is None:
            continue
        if _format_mass_scalar(ov) != _format_mass_scalar(nv):
            label = key.replace("_", " ")
            changed.append(
                f"- {label}: {_format_mass_scalar(ov) if ov is not None else '(none)'} → "
                f"{_format_mass_scalar(nv) if nv is not None else '(none)'}"
            )
    if not changed:
        return []
    return ["Mass properties changed:", *changed]


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
                "id": f.get("id"),
                "name": str(f.get("name") or "").strip() or None,
                "type": str(f.get("type") or "").strip() or None,
                "subtype": str(f.get("subtype") or "").strip() or None,
                "status": f.get("status"),
                "erased": f.get("erased"),
                "sheet": f.get("sheet"),
                "scale": f.get("scale"),
                "model": f.get("model"),
                "detail": f.get("detail"),
                "level": f.get("level"),
                "is_background": f.get("is_background"),
                "pattern_member_count": f.get("pattern_member_count"),
            }
            out["features"].append({k: v for k, v in row.items() if v is not None})
    bom_nodes = _bom_nodes(snapshot)
    if bom_nodes:
        out["bom"] = _slim_bom_nodes(bom_nodes)
    structure_rows = _structure_nodes(snapshot)
    if structure_rows:
        slim_struct: list[dict[str, Any]] = []
        for row in structure_rows:
            item = {
                "id": row.get("id"),
                "name": str(row.get("name") or "").strip() or None,
                "type": str(row.get("type") or "").strip() or None,
                "subtype": str(row.get("subtype") or row.get("subType") or "").strip()
                or None,
                "level": row.get("level"),
                "status": row.get("status"),
                "path": row.get("path"),
            }
            slim_struct.append({k: v for k, v in item.items() if v is not None})
        out["structure"] = slim_struct
    simp_reps = snapshot.get("simp_reps")
    if isinstance(simp_reps, dict) and simp_reps:
        slim_simp: dict[str, Any] = {}
        active = simp_reps.get("active")
        if isinstance(active, dict):
            slim_simp["active"] = {
                k: active[k]
                for k in ("id", "name", "is_master")
                if k in active and active.get(k) is not None
            }
        reps = simp_reps.get("representations")
        if isinstance(reps, list) and reps:
            slim_reps: list[dict[str, Any]] = []
            for rep in reps:
                if not isinstance(rep, dict):
                    continue
                row = {
                    k: rep.get(k)
                    for k in (
                        "id",
                        "name",
                        "type",
                        "temporary",
                        "default_action",
                        "instructions_available",
                    )
                    if rep.get(k) is not None
                }
                items = rep.get("items")
                if isinstance(items, list) and items:
                    row["items"] = [
                        dict(item)
                        for item in items
                        if isinstance(item, dict)
                    ]
                if row:
                    slim_reps.append(row)
            if slim_reps:
                slim_simp["representations"] = slim_reps
        if slim_simp:
            out["simp_reps"] = slim_simp
    constraints = snapshot.get("constraints")
    if isinstance(constraints, dict) and constraints:
        slim_cons: dict[str, Any] = {}
        if constraints.get("ok") is not None:
            slim_cons["ok"] = constraints.get("ok")
        if constraints.get("fileName") is not None:
            slim_cons["fileName"] = constraints.get("fileName")
        comps = constraints.get("components")
        if isinstance(comps, list) and comps:
            slim_comps: list[dict[str, Any]] = []
            for comp in comps:
                if not isinstance(comp, dict):
                    continue
                row = {
                    k: comp.get(k)
                    for k in (
                        "component_id",
                        "component_path",
                        "path",
                        "model_name",
                        "capture_status",
                        "error",
                        "placement",
                        "constraints",
                    )
                    if comp.get(k) is not None
                }
                if row:
                    slim_comps.append(row)
            if slim_comps:
                slim_cons["components"] = slim_comps
        if slim_cons:
            out["constraints"] = slim_cons
    relations = snapshot.get("relations")
    if isinstance(relations, dict) and relations:
        slim_rel: dict[str, Any] = {}
        if relations.get("ok") is not None:
            slim_rel["ok"] = relations.get("ok")
        if relations.get("fileName") is not None:
            slim_rel["fileName"] = relations.get("fileName")
        for key in ("normal", "post_regeneration"):
            vals = _relation_trim_lines(relations.get(key))
            if vals:
                slim_rel[key] = vals
            elif isinstance(relations.get(key), list):
                slim_rel[key] = []
        feat_rows = relations.get("features")
        if isinstance(feat_rows, list) and feat_rows:
            slim_feats: list[dict[str, Any]] = []
            for feat in feat_rows:
                if not isinstance(feat, dict):
                    continue
                row = {
                    k: feat.get(k)
                    for k in ("feature_id", "feature_name", "relations")
                    if feat.get(k) is not None
                }
                if row:
                    slim_feats.append(row)
            if slim_feats:
                slim_rel["features"] = slim_feats
        if slim_rel:
            out["relations"] = slim_rel
    dimensions = snapshot.get("dimensions")
    if isinstance(dimensions, list):
        out["dimensions"] = []
        for d in _iter_compare_dimensions(dimensions):
            row = {
                "symbol": d.get("symbol"),
                "value": d.get("value"),
                "units": d.get("units"),
                "feature_id": d.get("feature_id"),
                "feature_name": d.get("feature_name"),
            }
            out["dimensions"].append({k: v for k, v in row.items() if v is not None})
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
    mass_props = _mass_props(snapshot)
    if mass_props:
        out["mass"] = dict(mass_props)
    capture = snapshot.get("capture")
    if isinstance(capture, dict):
        slim_cap: dict[str, Any] = {}
        if capture.get("sheet_count") is not None:
            slim_cap["sheet_count"] = capture.get("sheet_count")
        if capture.get("drawing_models"):
            slim_cap["drawing_models"] = capture.get("drawing_models")
        ctx = capture.get("assembly_context")
        if isinstance(ctx, dict) and ctx:
            slim_cap["assembly_context"] = dict(ctx)
        if slim_cap:
            out["capture"] = slim_cap
    return out


def _blank_before_section(lines: list[str]) -> None:
    """Blank line between major outline sections (part / asm / drawing)."""
    if lines and lines[-1] != "":
        lines.append("")


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
            _blank_before_section(lines)
            lines.append("Referenced models:")
            lines.extend(model_lines)

        views = [f for f in features if _is_view_feature(f)]
        if _drawing_has_rich_inventory(features):
            # Full drawing inventory (sheets / views / notes / tables / …).
            # Nest by sheet so Toolkit "all sheets then all children" snapshots indent right.
            _blank_before_section(lines)
            lines.append("Drawing inventory:")
            nested = nest_drawing_inventory_by_sheet(
                [f for f in features if isinstance(f, dict)]
            )
            dims_listed = _snapshot_has_dimension_list(snapshot)
            inv_rows = [
                f
                for f in nested
                if _feature_type_label(f) != "DRAWING"
                and (not dims_listed or _feature_type_label(f) not in _DRAWING_DIM_TYPES)
            ]
            if inv_rows:
                lines.extend(_inventory_outline_line(f) for f in inv_rows)
            else:
                lines.append("- (none)")
            if views:
                visible = sum(
                    1
                    for v in views
                    if not (
                        v.get("erased") is True
                        or "ERASE" in str(v.get("status") or "").upper()
                    )
                )
                erased = len(views) - visible
                lines.append(
                    f"View count: {len(views)} total, {visible} visible, {erased} erased"
                )
        else:
            _blank_before_section(lines)
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
                lines.append(
                    f"View count: {len(views)} total, {visible} visible, {erased} erased"
                )
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
    else:
        struct_rows = _structure_nodes(snapshot)
        bom_nodes = _bom_nodes(snapshot)
        is_asm = (
            _is_assembly_snapshot(snapshot, identity)
            or bool(bom_nodes)
            or bool(struct_rows)
        )
        if struct_rows:
            # Assembly inventory (groups / components / status) — same as Details.
            _blank_before_section(lines)
            lines.append("Structure:")
            lines.extend(_inventory_outline_line(row) for row in struct_rows)
        elif bom_nodes:
            # Legacy BOM tree when inventory structure was not captured.
            _blank_before_section(lines)
            lines.append("Structure:")
            lines.extend(_format_bom_outline_lines(bom_nodes))
        _blank_before_section(lines)
        if is_asm and (bom_nodes or struct_rows):
            lines.append("Assembly features (non-component):")
        else:
            lines.append("Features:")
        if features:
            pattern_i = 0
            for feat in features:
                if _is_pattern_feature(feat):
                    pattern_i += 1
                    lines.append(
                        f"- {_feature_outline_label(feat, pattern_index=pattern_i)}"
                    )
                else:
                    lines.append(f"- {_feature_outline_label(feat)}")
        else:
            lines.append("- (none)")

    dimensions = snapshot.get("dimensions")
    # Drawing dimensions are listed in the inventory above; an empty "(none)" would contradict it.
    dims_in_inventory = drawing and any(
        _feature_type_label(f) in _DRAWING_DIM_TYPES for f in features if isinstance(f, dict)
    )
    if isinstance(dimensions, list) and not (dims_in_inventory and not dimensions):
        feat_labels = _feature_id_label_map(snapshot)
        dim_lines = [
            f"- {_dimension_outline_line(dim, feature_labels=feat_labels)}"
            for dim in _iter_compare_dimensions(dimensions)
        ]
        _blank_before_section(lines)
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
                _blank_before_section(lines)
                if current:
                    lines.append(f"Material: {current}")
                elif len(names) == 1:
                    lines.append(f"Material: {names[0]}")
                else:
                    lines.append("Materials: " + ", ".join(names))
        mass_lines = _mass_outline_lines(snapshot)
        if mass_lines:
            _blank_before_section(lines)
            lines.extend(mass_lines)

    param_rows = _iter_compare_parameters(parameters, drawing=drawing)
    if param_rows or drawing:
        # Always show Parameters for drawings when other model params exist;
        # skip empty "(none)" noise when drawing synthetics were the only ones.
        if param_rows:
            _blank_before_section(lines)
            lines.append("Parameters:")
            for param in param_rows:
                lines.append(f"- {_parameter_outline_line(param)}")
        elif not drawing:
            _blank_before_section(lines)
            lines.append("Parameters:")
            lines.append("- (none)")

    if not drawing:
        # End of outline — easy to find; keep clear of Structure so exclude
        # rules are not read as component deletes.
        simp_lines = _simp_reps_outline_lines(snapshot)
        if simp_lines:
            _blank_before_section(lines)
            lines.extend(simp_lines)
        cons_lines = _constraints_outline_lines(snapshot)
        if cons_lines:
            _blank_before_section(lines)
            lines.extend(cons_lines)
        rel_lines = _relations_outline_lines(snapshot)
        if rel_lines:
            _blank_before_section(lines)
            lines.extend(rel_lines)

    return "\n".join(lines) if lines else "(empty snapshot)"

CHECKIN_BATCH_COMMENT_SYSTEM = (
    "You write a single CreoPDM check-in comment. "
    "Input is one short change note per file already checked by CreoPDM. "
    "Reply with only the comment text: concise, factual, past tense, no markdown "
    "headings, no preamble (do not start with Comment: or Here is). "
    "Cover every file that has a real change note; omit skipped/error-only lines "
    "unless that is the only content. Prefer one short paragraph or a few bullets."
)


def build_checkin_batch_comment_user_prompt(
    notes: list[dict[str, str]],
) -> str:
    """User message for synthesizing one check-in comment from per-file AI notes."""
    lines: list[str] = [
        "Write one check-in comment that summarizes these per-file change notes:",
        "",
    ]
    for note in notes:
        if not isinstance(note, dict):
            continue
        name = str(note.get("filename") or "").strip() or "(unnamed)"
        summary = str(note.get("summary") or "").strip()
        if not summary:
            continue
        lines.append(f"=== {name} ===")
        lines.append(summary)
        lines.append("")
    if len(lines) <= 2:
        raise ValidationAppError("No per-file change notes to summarize.")
    return "\n".join(lines).rstrip() + "\n"


def format_checkin_batch_comment_fallback(notes: list[dict[str, str]]) -> str:
    """Plain bullet list when the synthesize Ollama call fails."""
    bullets: list[str] = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        name = str(note.get("filename") or "").strip() or "(unnamed)"
        summary = str(note.get("summary") or "").strip()
        if not summary:
            continue
        # Keep each file to one line when possible.
        one = " ".join(summary.split())
        if len(one) > 220:
            one = one[:217].rstrip() + "…"
        bullets.append(f"- {name}: {one}")
    if not bullets:
        raise ValidationAppError("No per-file change notes to summarize.")
    return "Check-in summary:\n" + "\n".join(bullets)


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: OLD then NEW plain-language outlines (settings hold instructions).

    Modifications Ask AI and Check In Ask AI for comment both use this —
    parts, assemblies, and drawings share prepare → outline → computed diff.
    """
    older_label = (older_revision or "").strip()
    newer_label = (newer_revision or "").strip()
    if not older_label or older_label in {"—", "-"}:
        older_label = "older"
    if not newer_label or newer_label in {"—", "-"}:
        newer_label = "newer"
    older_prepared = prepare_snapshot_for_compare(older_snapshot)
    newer_prepared = prepare_snapshot_for_compare(newer_snapshot)
    older_text = format_snapshot_compare_text(older_prepared)
    newer_text = format_snapshot_compare_text(newer_prepared)
    diff_text = format_snapshot_compare_diff_text(older_prepared, newer_prepared)
    # Labeled facts only. All narrative / cite rules live in the saved
    # System Settings → AI snapshot compare prompt (system message).
    return (
        f"=== OLD ({older_label}) ===\n"
        f"{older_text}\n\n"
        f"=== NEW ({newer_label}) ===\n"
        f"{newer_text}\n\n"
        f"{diff_text}"
    )
