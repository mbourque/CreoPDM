"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

import re
from typing import Any

from creopdm.exceptions import ValidationAppError
from creopdm.utils.bom_match import normalize_bom_compare_filename

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


def _is_drawing_inventory_compare_feature(feat: dict[str, Any]) -> bool:
    """Views / notes / tables / detail items — not sheet shells or dim duplicates."""
    if not isinstance(feat, dict):
        return False
    return _feature_type_label(feat) not in _DRAWING_INVENTORY_SKIP_COMPARE


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


def _inventory_outline_line(row: dict[str, Any]) -> str:
    """Indented inventory line (same nesting idea as Details inventory tables)."""
    name = str(row.get("name") or "").strip() or "—"
    typ = str(row.get("type") or "").strip()
    status = str(row.get("status") or "").strip()
    level = _inventory_level(row)
    indent = "  " * max(0, level - 1)
    nest = "└ " if level > 1 else ""
    extras: list[str] = []
    if typ and typ.upper() not in name.upper():
        extras.append(typ)
    if status and status.upper() not in {"ACTIVE", ""}:
        extras.append(status)
    sheet = row.get("sheet")
    if sheet not in (None, "") and typ.upper() != "SHEET":
        extras.append(f"sheet {sheet}")
    detail = str(row.get("detail") or "").strip()
    if detail and typ.upper() == "NOTE":
        short = detail if len(detail) <= 80 else detail[:77] + "…"
        extras.append(short)
    suffix = f" ({', '.join(extras)})" if extras else ""
    return _append_creo_feature_id(f"{indent}- {nest}{name}{suffix}", row)


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


def _simp_reps_outline_lines(snapshot: dict[str, Any]) -> list[str]:
    """Assembly simplified representation definitions (not BOM membership)."""
    simp = snapshot.get("simp_reps")
    if not isinstance(simp, dict):
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
        for d in _iter_compare_dimensions(
            older.get("dimensions") if isinstance(older.get("dimensions"), list) else []
        )
        if str(d.get("symbol") or "").strip()
    }
    newer_dims = {
        str(d.get("symbol") or "").strip(): d
        for d in _iter_compare_dimensions(
            newer.get("dimensions") if isinstance(newer.get("dimensions"), list) else []
        )
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
        lines.extend(_bullet_block("Components removed", comp_removed))
        lines.extend(_bullet_block("Components added", comp_added))
        lines.extend(_bullet_block("Components quantity changed", comp_qty_changed))
    lines.extend(
        [
            *_bullet_block("Features removed", feat_removed),
            *_bullet_block("Features added", feat_added),
            *_bullet_block("Dimensions removed", dim_removed),
            *_bullet_block("Dimensions changed (same symbol)", dim_changed),
            *_bullet_block("Dimensions added", dim_added),
        ]
    )
    return "\n".join(lines)


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
        if _drawing_has_rich_inventory(features):
            # Full drawing inventory (sheets / views / notes / tables / …).
            lines.append("Drawing inventory:")
            inv_rows = [
                f
                for f in features
                if _feature_type_label(f) not in {"DRAWING", "DIMENSION", "DIM"}
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
            lines.append("Structure:")
            lines.extend(_inventory_outline_line(row) for row in struct_rows)
        elif bom_nodes:
            # Legacy BOM tree when inventory structure was not captured.
            lines.append("Structure:")
            lines.extend(_format_bom_outline_lines(bom_nodes))
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
    if isinstance(dimensions, list):
        feat_labels = _feature_id_label_map(snapshot)
        dim_lines = [
            f"- {_dimension_outline_line(dim, feature_labels=feat_labels)}"
            for dim in _iter_compare_dimensions(dimensions)
        ]
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

    if not drawing:
        # End of outline — easy to find; keep clear of Structure so exclude
        # rules are not read as component deletes.
        simp_lines = _simp_reps_outline_lines(snapshot)
        if simp_lines:
            lines.extend(simp_lines)

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
        f"=== OLD snapshot ({older_label}) ===\n"
        f"{older_text}\n\n"
        f"=== NEW snapshot ({newer_label}) ===\n"
        f"{newer_text}\n\n"
        f"{diff_text}"
    )
