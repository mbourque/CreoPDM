"""Overview / Sketch-tab view model for a Creo 2D section (.sec) collected by the Toolkit.

Contract: Toolkit Companion 0.5.0 ``domains.sketch`` (provisional until checked against
real responses). A ``null`` field means the Toolkit cannot supply it — show "—", never
zero or false.
"""

from __future__ import annotations

from typing import Any

_ENTITY_ORDER = ("line", "arc", "circle", "spline", "point", "centerline", "text", "other")
_DIMENSION_TYPE_LABELS = {
    "linear": "Linear",
    "radial": "Radius",
    "diameter": "Diameter",
    "angular": "Angle",
    "other": "Other",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _dimension_value(row: dict[str, Any]) -> str:
    display = _text(row.get("display"))
    if display:
        return display
    number = _number(row.get("value"))
    return _fmt(number) if number is not None else "—"


def _yes_no(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "—"


def _tolerance(value: Any) -> str:
    if isinstance(value, dict):
        low, high = _number(value.get("lower")), _number(value.get("upper"))
        if low is not None or high is not None:
            return f"{_fmt(low) if low is not None else '—'} / {_fmt(high) if high is not None else '—'}"
        text = _text(value.get("text") or value.get("display"))
        return text or "—"
    text = _text(value)
    return text or "—"


def _partial_text(raw: Any) -> str:
    """Readable list of the parts the Toolkit could not read (strings or small dicts)."""
    if not isinstance(raw, list):
        return ""
    parts: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            what = _text(item.get("part") or item.get("domain") or item.get("name") or item.get("field"))
            func = _text(item.get("function") or item.get("func"))
            code = item.get("return_code", item.get("rc", item.get("code")))
            where = _text(item.get("id") or item.get("entity_id") or item.get("dimension_id"))
            reason = f"{func}={code}" if func and code is not None else func or _text(item.get("error"))
            bits = [bit for bit in (what, reason, f"id {where}" if where else "") if bit]
            parts.append(" — ".join(bits[:1]) + (f" ({', '.join(bits[1:])})" if len(bits) > 1 else ""))
        else:
            text = _text(item)
            if text:
                parts.append(text)
    return "; ".join(part for part in parts if part)


def sketch_error(sketch: Any) -> str:
    """The Toolkit's reason when it could not read the sketch ("" when there is none)."""
    if isinstance(sketch, dict) and sketch.get("ok") is False:
        return _text(sketch.get("error")) or "the Toolkit could not read this sketch"
    return ""


def sketch_overview(sketch: Any) -> dict[str, Any] | None:
    """Rows for the Overview tab and the Sketch tab, or None when there is no sketch data."""
    if not isinstance(sketch, dict) or sketch.get("ok") is False:
        return None
    units = sketch.get("units") if isinstance(sketch.get("units"), dict) else {}
    length_unit = _text(units.get("length"))  # may be empty: do not guess a unit

    size = ""
    outline = sketch.get("outline")
    if isinstance(outline, dict):
        width, height = _number(outline.get("width")), _number(outline.get("height"))
        if width is not None and height is not None:
            size = f"{_fmt(width)} × {_fmt(height)}" + (f" {length_unit}" if length_unit else "")

    entities = sketch.get("entities") if isinstance(sketch.get("entities"), dict) else {}
    raw_counts = entities.get("counts") if isinstance(entities.get("counts"), dict) else {}
    counts: list[dict[str, Any]] = []
    for key in _ENTITY_ORDER:
        number = _int(raw_counts.get(key))
        if number:
            counts.append({"type": key, "label": key.capitalize(), "count": number})
    for key, value in raw_counts.items():
        number = _int(value)
        if key not in _ENTITY_ORDER and number:
            counts.append({"type": str(key), "label": str(key).capitalize(), "count": number})
    total = _int(entities.get("total"))
    if total is None and counts:
        total = sum(item["count"] for item in counts)
    entity_text = ", ".join(f"{item['count']} {item['type']}" for item in counts)

    dimensions: list[dict[str, str]] = []
    raw_dims = sketch.get("dimensions")
    dimension_known = isinstance(raw_dims, list)
    for row in raw_dims if isinstance(raw_dims, list) else []:
        if not isinstance(row, dict):
            continue
        kind = _text(row.get("type")).lower()
        ids = row.get("entity_ids")
        dimensions.append(
            {
                "id": _text(row.get("id")) or "—",
                "type": _DIMENSION_TYPE_LABELS.get(kind, kind.capitalize() or "—"),
                "value": _dimension_value(row),
                "reference": _yes_no(row.get("reference")),
                "tolerance": _tolerance(row.get("tolerance")),
                "entities": ", ".join(str(item) for item in ids) if isinstance(ids, list) else "",
            }
        )

    constraint_types: dict[str, int] = {}
    raw_constraints = sketch.get("constraints")
    for row in raw_constraints if isinstance(raw_constraints, list) else []:
        if isinstance(row, dict):
            kind = _text(row.get("type")).lower() or "other"
            constraint_types[kind] = constraint_types.get(kind, 0) + 1
    constraint_known = isinstance(raw_constraints, list)
    constraint_total = sum(constraint_types.values()) if constraint_known else None
    constraint_text = ", ".join(
        f"{count} {kind}" for kind, count in sorted(constraint_types.items(), key=lambda kv: (-kv[1], kv[0]))
    )

    loops = sketch.get("loops") if isinstance(sketch.get("loops"), dict) else None
    closed = _int(loops.get("closed")) if loops else None
    open_loops = _int(loops.get("open")) if loops else None
    loops_text = ""
    if closed is not None or open_loops is not None:
        loops_text = f"{closed if closed is not None else '—'} closed, {open_loops if open_loops is not None else '—'} open"

    status = sketch.get("status") if isinstance(sketch.get("status"), dict) else {}
    fully = status.get("fully_dimensioned")
    view = {
        "size": size,
        "length_unit": length_unit,
        "entity_total": total,
        "entity_counts": counts,
        "entity_text": entity_text,
        "construction_count": _int(entities.get("construction_count")),
        "entities_truncated": bool(entities.get("truncated")),
        "dimensions": dimensions,
        # None = the Toolkit sent no list (unknown) — shown as "—", not 0.
        "dimension_count": len(dimensions) if dimension_known else None,
        "constraint_total": constraint_total,
        "constraint_types": constraint_types,
        "constraint_text": constraint_text,
        "loops": loops_text,
        "closed_loops": closed,
        # Only shown when the Toolkit reported a real boolean.
        "fully_dimensioned": "Yes" if fully is True else "No" if fully is False else "",
        # Parts the Toolkit could not read ("entities (ProSectionEntityIdsGet=-2)" …).
        # Only partial_missing means "something could not be read" — never notes.
        "partial": _partial_text(sketch.get("partial_missing")),
        # sketch["notes"] (how the Toolkit obtained the data) is informational only and is
        # deliberately never shown — it is not a warning and there is nothing to act on.
        # True only when the Toolkit regenerated the section in Creo to read it.
        "regenerated": status.get("regenerated") is True,
    }
    has_data = any(
        (
            size,
            total,
            dimensions,
            constraint_total,
            loops_text,
            view["fully_dimensioned"],
        )
    )
    return view if has_data else None
