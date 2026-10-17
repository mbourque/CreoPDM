"""Map CreoPDM Toolkit ``/collect`` JSON into a gatherModelMetadata-shaped snapshot.

Used by the local agent ``/toolkit/snapshot`` proxy so the browser can POST the
same ``CreoMetadataRequest`` body as Creo.JS gather. Probes / creo_inventory stay
untouched as the Creo.JS fallback.
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_TOOLKIT_BASE_URL = "http://127.0.0.1:8767"

_CAD_STRUCTURE_TIP_RE = re.compile(
    r"\.(prt|asm|mfg|drw|frm|sec|lay|neu|xas|xpr)(\.\d+)?$",
    re.IGNORECASE,
)


def domains_for_filename(filename: str) -> str:
    """Comma-separated Toolkit collect domains for a Creo tip name."""
    name = (filename or "").strip().lower()
    # Strip Creo numbered saves: shaft.prt.2 → shaft.prt
    parts = name.rsplit(".", 2)
    if len(parts) == 3 and parts[2].isdigit():
        name = f"{parts[0]}.{parts[1]}"
    if name.endswith(".sec"):
        # 2D sketch: any other domain answers "does not apply to a SECTION".
        return "identity,sketch"
    if name.endswith(".mfg"):
        return "identity,parameters,mfg,units"
    if name.endswith(".drw"):
        return "identity,parameters,drawing,units"
    if name.endswith(".asm"):
        # bom is opt-in on Toolkit /collect defaults; CreoPDM asks for it on .asm.
        return "identity,parameters,features,dimensions,structure,bom,constraints,units"
    if name.endswith(".prt"):
        return "identity,parameters,features,dimensions,materials,mass,units"
    return "identity,parameters,features,dimensions,units"


def _ok_domain(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    domains = payload.get("domains")
    if not isinstance(domains, dict):
        return None
    block = domains.get(name)
    if not isinstance(block, dict) or block.get("ok") is False:
        return None
    if block.get("ok") is True:
        return block
    # Some domains may omit ok when nested under a successful collect.
    if "error" in block:
        return None
    return block


def _list_field(block: dict[str, Any] | None, *keys: str) -> list[Any] | None:
    if not block:
        return None
    for key in keys:
        value = block.get(key)
        if isinstance(value, list):
            return value
    return None


def _structure_row_name(row: dict[str, Any]) -> str:
    for key in (
        "name",
        "model_name",
        "file_name",
        "filename",
        "fileName",
        "component_name",
        "tip",
        "model",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _structure_row_is_skeleton(row: dict[str, Any], typ: str, sub: str) -> bool:
    """True when Toolkit marked a structure member as a skeleton model."""
    if typ == "SKELETON" or sub == "SKELETON":
        return True
    flag = row.get("is_skeleton")
    if flag is True or flag == 1:
        return True
    if isinstance(flag, str) and flag.strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def _structure_row_is_harness(row: dict[str, Any], typ: str, sub: str) -> bool:
    """True when Toolkit marked a structure member as a cabling harness."""
    if typ in {"HARNESS", "HARNESS_PART"} or sub in {"HARNESS", "HARNESS_PART"}:
        return True
    role = str(row.get("role") or row.get("model_role") or "").strip().upper()
    if role in {"HARNESS", "HARNESS_PART"}:
        return True
    flag = row.get("is_harness")
    if flag is True or flag == 1:
        return True
    if isinstance(flag, str) and flag.strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def normalize_toolkit_structure_row(row: dict[str, Any]) -> dict[str, Any]:
    """Align Toolkit structure rows with Creo.JS Structure (tip name + PART/ASSEMBLY).

    CreoPDM drops COMPONENT rows whose name is not a CAD tip (datums / CSYS noise).
    Toolkit often emits type COMPONENT with ``shaft.prt`` — promote those to PART/ASSEMBLY
    so the Details Structure tab is not empty after filter_assembly_structure_rows.

    Skeleton / harness tips are still ``*.prt``; never overwrite Toolkit ``SKELETON`` /
    ``HARNESS`` with PART from the extension alone.
    """
    out = dict(row)
    name = _structure_row_name(out)
    typ = str(out.get("type") or "").strip().upper()
    role = str(out.get("role") or "").strip().upper()
    sub = str(out.get("subtype") or out.get("subType") or out.get("model_type") or "").strip().upper()
    lower = name.lower()
    skeleton = _structure_row_is_skeleton(out, typ, sub)
    harness = _structure_row_is_harness(out, typ, sub)

    if _CAD_STRUCTURE_TIP_RE.search(lower):
        if re.search(r"\.asm(\.\d+)?$", lower):
            typ = "ASSEMBLY"
        elif re.search(r"\.mfg(\.\d+)?$", lower):
            typ = "MFG"
        elif re.search(r"\.prt(\.\d+)?$", lower):
            # Keep Toolkit skeleton / harness typing.
            if skeleton or typ == "SKELETON":
                typ = "SKELETON"
                if not sub:
                    sub = "SKELETON"
            elif harness or typ in {"HARNESS", "HARNESS_PART"}:
                typ = "HARNESS"
                if not sub:
                    sub = "HARNESS"
            elif typ in {"", "COMPONENT", "FEATURE", "PART"}:
                typ = "PART"
    elif role in {"REF_MODEL", "WORKPIECE", "FIXTURE"}:
        if name and not _CAD_STRUCTURE_TIP_RE.search(name):
            name = f"{name}.prt"
        if role == "WORKPIECE":
            typ = "WORKPIECE"
        elif role == "FIXTURE":
            typ = "FIXTURE"
        else:
            typ = "PART"
    elif typ in {"COMPONENT", "FEATURE", ""} and name:
        if "ASM" in sub or sub == "ASSEMBLY":
            if not _CAD_STRUCTURE_TIP_RE.search(name):
                name = f"{name}.asm"
            typ = "ASSEMBLY"
        elif sub == "SKELETON" or skeleton:
            if not _CAD_STRUCTURE_TIP_RE.search(name):
                name = f"{name}.prt"
            typ = "SKELETON"
            sub = "SKELETON"
        elif sub in {"HARNESS", "HARNESS_PART"} or harness:
            if not _CAD_STRUCTURE_TIP_RE.search(name):
                name = f"{name}.prt"
            typ = "HARNESS"
            sub = "HARNESS"
        elif "PRT" in sub or sub == "PART" or sub in {"MDL_PART", "SOLID"}:
            if not _CAD_STRUCTURE_TIP_RE.search(name):
                name = f"{name}.prt"
            typ = "PART"

    if name:
        out["name"] = name
    if typ:
        out["type"] = typ
    if sub:
        out["subtype"] = sub
    return out


def normalize_toolkit_structure_rows(
    rows: list[Any] | None,
) -> list[dict[str, Any]] | None:
    if rows is None:
        return None
    return [
        normalize_toolkit_structure_row(row)
        for row in rows
        if isinstance(row, dict)
    ]


def _drawing_sheet_key(row: dict[str, Any]) -> str | None:
    """Stable sheet bucket key from a SHEET row or a sheet-tagged child."""
    sheet = row.get("sheet")
    if sheet not in (None, ""):
        return str(sheet).strip() or None
    rid = str(row.get("id") or "").strip()
    if rid.lower().startswith("sheet:"):
        key = rid.split(":", 1)[1].strip()
        return key or None
    return None


def nest_drawing_inventory_by_sheet(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Put views/notes/tables under their sheet (Toolkit often dumps sheets then children).

    Outline indent uses ``level`` + list order. When every SHEET is level 1 and every
    view/note is level 2 *after* the last sheet, the UI piles all children under Sheet N
    even though each row already has the correct ``sheet`` field. Rebuild order/levels
    from that field (same idea as Creo.JS ``buildDrawingInventory``).
    """
    if not rows:
        return rows
    if not any(str(r.get("type") or "").upper() == "SHEET" for r in rows):
        return rows

    roots: list[dict[str, Any]] = []
    sheets: dict[str, dict[str, Any]] = {}
    sheet_order: list[str] = []
    children: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []

    def _remember_sheet(key: str, row: dict[str, Any] | None = None) -> None:
        if key not in sheets:
            sheet_order.append(key)
            if row is not None:
                sheets[key] = row
            else:
                try:
                    sheet_num: Any = int(key)
                except (TypeError, ValueError):
                    sheet_num = key
                sheets[key] = {
                    "id": f"sheet:{key}",
                    "name": f"Sheet {key}",
                    "type": "SHEET",
                    "level": 1,
                    "sheet": sheet_num,
                    "status": "ACTIVE",
                }
        elif row is not None:
            sheets[key] = row

    for row in rows:
        item = dict(row)
        typ = str(item.get("type") or "").upper()
        if typ == "SHEET":
            key = _drawing_sheet_key(item)
            if not key:
                roots.append(item)
                continue
            item["level"] = 1
            if item.get("sheet") in (None, ""):
                try:
                    item["sheet"] = int(key)
                except (TypeError, ValueError):
                    item["sheet"] = key
            _remember_sheet(key, item)
            continue
        if typ == "DRAWING":
            item["level"] = 1
            roots.append(item)
            continue
        key = _drawing_sheet_key(item)
        if key is None:
            unassigned.append(item)
            continue
        _remember_sheet(key)
        children.setdefault(key, []).append(item)

    def _sheet_sort_key(key: str) -> tuple[int, Any]:
        try:
            return (0, int(key))
        except (TypeError, ValueError):
            return (1, key)

    out: list[dict[str, Any]] = list(roots)
    for key in sorted(sheet_order, key=_sheet_sort_key):
        sheet_row = dict(sheets[key])
        sheet_row["level"] = 1
        out.append(sheet_row)
        for child in children.get(key, []):
            nested = dict(child)
            nested["level"] = 2
            out.append(nested)

    if unassigned:
        out.append(
            {
                "id": "sheet:unassigned",
                "name": "Unassigned sheet",
                "type": "SHEET",
                "level": 1,
                "sheet": None,
                "status": "ACTIVE",
                "detail": "items with no sheet number",
            }
        )
        for child in unassigned:
            nested = dict(child)
            nested["level"] = 2
            out.append(nested)
    return out


def normalize_toolkit_feature_rows(
    rows: list[Any] | None,
) -> list[dict[str, Any]] | None:
    """Ensure feature/drawing inventory rows have level ≥ 1 for Details indent."""
    if rows is None:
        return None
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        level = item.get("level")
        try:
            level_n = int(level) if level is not None else 1
        except (TypeError, ValueError):
            level_n = 1
        if level_n < 1:
            level_n = 1
        item["level"] = level_n
        out.append(item)
    if any(str(i.get("type") or "").upper() == "SHEET" for i in out):
        out = nest_drawing_inventory_by_sheet(out)
    return out


def _bom_node_filename(node: dict[str, Any]) -> str:
    for key in ("filename", "file_name", "fileName", "name", "model_name"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_toolkit_bom_node(node: dict[str, Any]) -> dict[str, Any] | None:
    """Align Toolkit /bom nodes with Creo.JS creoGatherBomTree shape."""
    filename = _bom_node_filename(node)
    if not filename:
        return None
    try:
        qty = float(node.get("quantity") if node.get("quantity") is not None else 1.0)
    except (TypeError, ValueError):
        qty = 1.0
    dep = str(node.get("dependency_type") or "ASSEMBLY_MEMBER").strip() or "ASSEMBLY_MEMBER"
    children_raw = node.get("children")
    children: list[dict[str, Any]] = []
    if isinstance(children_raw, list):
        for child in children_raw:
            if not isinstance(child, dict):
                continue
            normalized = normalize_toolkit_bom_node(child)
            if normalized is not None:
                children.append(normalized)
    out: dict[str, Any] = {
        "filename": filename,
        "quantity": qty,
        "dependency_type": dep,
        "children": children,
    }
    # Optional Toolkit extras (Details / AI ignore unknown keys; keep type for UI).
    typ = str(node.get("type") or "").strip()
    if typ:
        out["type"] = typ
    if "expanded" in node:
        out["expanded"] = bool(node.get("expanded"))
    leaf_reason = node.get("leaf_reason")
    if isinstance(leaf_reason, str) and leaf_reason.strip():
        out["leaf_reason"] = leaf_reason.strip()
    return out


def normalize_toolkit_bom(
    rows: list[Any] | None,
) -> list[dict[str, Any]] | None:
    """Return Creo.JS-shaped BOM tree (one ASSEMBLY_ROOT wrapper) or None."""
    if rows is None:
        return None
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = normalize_toolkit_bom_node(row)
        if normalized is not None:
            out.append(normalized)
    return out or None


_MASS_KEY_ALIASES = {
    "mass": "mass",
    "volume": "volume",
    "density": "density",
    "surface_area": "surface_area",
    "surfacearea": "surface_area",
    "area": "surface_area",
    "gravity_center": "gravity_center",
    "gravitycenter": "gravity_center",
    "cog": "gravity_center",
    "center_of_gravity": "gravity_center",
    "principal_moments": "principal_moments",
    "principalmoments": "principal_moments",
}


def normalize_toolkit_mass(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """Flatten Toolkit /mass into Details Mass-tab keys (mass/volume/density/…)."""
    if not isinstance(block, dict):
        return None
    skip = {"ok", "filename", "error", "partial", "partial_missing", "type"}
    candidates: list[dict[str, Any]] = [block]
    for nest_key in ("mass", "properties", "mass_properties", "MassProperty", "data"):
        nested = block.get(nest_key)
        if isinstance(nested, dict):
            candidates.append(nested)

    out: dict[str, Any] = {}
    for src in candidates:
        for key, value in src.items():
            if value is None:
                continue
            key_l = str(key or "").strip()
            if not key_l or key_l.lower() in skip:
                continue
            # Domain-level mass: number — keep as mass.
            if key_l.lower() == "mass" and isinstance(value, (int, float)) and not isinstance(
                value, bool
            ):
                out.setdefault("mass", value)
                continue
            if isinstance(value, dict):
                continue
            canon = _MASS_KEY_ALIASES.get(key_l.lower().replace("-", "_"))
            if not canon:
                # Accept already-canonical or pass through unknown scalars.
                if key_l.lower() in _MASS_KEY_ALIASES.values():
                    canon = key_l.lower()
                else:
                    continue
            out.setdefault(canon, value)

    useful = ("mass", "volume", "density", "surface_area", "gravity_center", "principal_moments")
    if not any(k in out for k in useful):
        return None
    return out


def normalize_toolkit_dimensions(rows: list[Any] | None) -> list[dict[str, Any]]:
    """Toolkit dimensions domain → compare rows (symbol, value, units, feature)."""
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            symbol = row.get("name") if isinstance(row.get("name"), str) else ""
        symbol = str(symbol or "").strip()
        if not symbol:
            continue
        item: dict[str, Any] = {"symbol": symbol}
        value = row.get("value")
        if value is None:
            value = row.get("dim_value", row.get("dimValue"))
        if value is not None:
            item["value"] = value
        units = row.get("units", row.get("unit"))
        if isinstance(units, str) and units.strip():
            item["units"] = units.strip()
        fid = row.get("feature_id", row.get("featureId", row.get("owner_id")))
        if fid is not None and fid != "":
            try:
                item["feature_id"] = int(fid)
            except (TypeError, ValueError):
                item["feature_id"] = fid
        fname = row.get("feature_name", row.get("featureName", row.get("owner_name")))
        if isinstance(fname, str) and fname.strip():
            item["feature_name"] = fname.strip()
        for key in ("dim_type", "tolerance_type", "id"):
            if row.get(key) is not None:
                item[key] = row[key]
        limits = row.get("tolerance_limits")
        if isinstance(limits, dict):
            item["tolerance_limits"] = limits
        out.append(item)
    return out


def _identity_file_name(identity: dict[str, Any] | None) -> str:
    """Toolkit may use file_name, filename, fileName, or full_name."""
    if not isinstance(identity, dict):
        return ""
    for key in ("file_name", "filename", "fileName", "full_name", "FullName"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def toolkit_snapshot_reject_reason(
    payload: dict[str, Any] | None,
    *,
    fallback_filename: str = "",
) -> str:
    """Short reason when map_toolkit_collect_to_snapshot returns None."""
    tip = str(fallback_filename or "").strip()
    if not isinstance(payload, dict):
        return "toolkit_snapshot_unusable: empty Toolkit response"
    if payload.get("ok") is False:
        err = payload.get("error") or payload.get("message") or ""
        domains = payload.get("domains")
        if isinstance(domains, dict):
            ident = domains.get("identity")
            if isinstance(ident, dict) and ident.get("error"):
                err = ident.get("error") or err
        err_s = str(err or "").strip()
        if err_s:
            return f"toolkit_collect_failed: {err_s}"
        return f"toolkit_collect_failed: ok=false ({tip or 'no tip'})"
    identity_block = payload.get("domains")
    if isinstance(identity_block, dict):
        ident = identity_block.get("identity")
        if isinstance(ident, dict) and ident.get("ok") is False:
            err = str(ident.get("error") or ident.get("message") or "").strip()
            if err:
                return f"toolkit_identity_failed: {err}"
            return "toolkit_identity_failed"
    if not tip and not str(payload.get("fileName") or "").strip():
        return "toolkit_snapshot_unusable: missing identity/file_name"
    return "toolkit_snapshot_unusable: could not map collect payload"


def map_toolkit_collect_to_snapshot(
    payload: dict[str, Any] | None,
    *,
    fallback_filename: str = "",
) -> dict[str, Any] | None:
    """Return a Creo.JS-gather-shaped snapshot, or None when identity is missing."""
    if not isinstance(payload, dict):
        return None
    # Top-level ok:false usually means retrieve failed — nothing usable to map.
    if payload.get("ok") is False:
        return None

    identity_block = _ok_domain(payload, "identity")
    identity: dict[str, Any] | None = None
    if identity_block and isinstance(identity_block.get("identity"), dict):
        identity = dict(identity_block["identity"])
    elif isinstance(payload.get("identity"), dict):
        identity = dict(payload["identity"])
    elif identity_block and isinstance(identity_block, dict):
        # Some Toolkit builds put tip fields on the domain root, not nested.
        identity = {
            k: v
            for k, v in identity_block.items()
            if k not in {"ok", "error", "partial", "partial_missing", "timings_ms"}
        } or None

    tip = (
        str(fallback_filename or "").strip()
        or str(payload.get("fileName") or payload.get("filename") or "").strip()
    )
    if not identity:
        # Collect still asked for this tip — keep a minimal identity so other
        # domains (features / mass) are not discarded for a naming quirk.
        if tip:
            identity = {"file_name": tip}
        else:
            return None
    file_name = _identity_file_name(identity)
    if not file_name and tip:
        identity = {**identity, "file_name": tip}
        file_name = tip
    if not file_name:
        return None
    identity = {**identity, "file_name": file_name}
    # Toolkit cabling harness: identity-only stub (no Retrieve) with model_role HARNESS.
    if payload.get("harness") is True or str(identity.get("identity_source") or "").strip().lower() == "file_header":
        role = str(identity.get("model_role") or identity.get("subtype") or "").strip().upper()
        if role in {"", "PART", "SOLID"} or payload.get("harness") is True:
            identity["model_role"] = "HARNESS"
        identity.setdefault("model_type", "PART")

    parameters_block = _ok_domain(payload, "parameters")
    parameters = _list_field(parameters_block, "parameters") or []

    features = normalize_toolkit_feature_rows(
        _list_field(_ok_domain(payload, "features"), "features")
    )
    structure = normalize_toolkit_structure_rows(
        _list_field(
            _ok_domain(payload, "structure"),
            "structure",
            "features",
            "components",
            "rows",
            "items",
            "members",
        )
    )

    bom_block = _ok_domain(payload, "bom")
    bom = normalize_toolkit_bom(
        _list_field(bom_block, "bom", "tree", "nodes", "items", "children")
    )
    # Toolkit may put a single root object under domains.bom.bom instead of a list.
    if bom is None and bom_block and isinstance(bom_block.get("bom"), dict):
        bom = normalize_toolkit_bom([bom_block["bom"]])

    drawing_block = _ok_domain(payload, "drawing")
    if drawing_block:
        draw_feats = _list_field(drawing_block, "features")
        if draw_feats is not None:
            features = normalize_toolkit_feature_rows(draw_feats)

    mfg_block = _ok_domain(payload, "mfg")
    if mfg_block:
        mfg_feats = _list_field(mfg_block, "features")
        if mfg_feats is not None:
            features = normalize_toolkit_feature_rows(mfg_feats)
        models = normalize_toolkit_structure_rows(_list_field(mfg_block, "models"))
        if models is not None:
            structure = models

    materials_block = _ok_domain(payload, "materials")
    materials = None
    if materials_block:
        if isinstance(materials_block.get("materials"), dict):
            materials = materials_block["materials"]
        elif any(k in materials_block for k in ("assigned", "material", "name")):
            materials = {
                k: v
                for k, v in materials_block.items()
                if k not in {"ok", "fileName", "error", "partial", "partial_missing"}
            } or None

    mass = normalize_toolkit_mass(_ok_domain(payload, "mass"))

    units_block = _ok_domain(payload, "units")
    units = None
    if units_block:
        if isinstance(units_block.get("units"), dict):
            units = units_block["units"]
        else:
            units = {
                k: v
                for k, v in units_block.items()
                if k not in {"ok", "fileName", "error", "partial", "partial_missing"}
            } or None

    constraints_block = _ok_domain(payload, "constraints")
    constraints = None
    if constraints_block:
        if isinstance(constraints_block.get("constraints"), dict):
            constraints = constraints_block["constraints"]
        elif isinstance(constraints_block.get("constraints"), list):
            constraints = {"items": constraints_block["constraints"]}
        else:
            constraints = {
                k: v
                for k, v in constraints_block.items()
                if k not in {"ok", "fileName", "error", "partial", "partial_missing"}
            } or None

    dimensions = normalize_toolkit_dimensions(
        _list_field(_ok_domain(payload, "dimensions"), "dimensions", "dims", "items")
    )

    simp_block = _ok_domain(payload, "simp_reps")
    simp_reps = None
    if simp_block:
        if isinstance(simp_block.get("simp_reps"), dict):
            simp_reps = simp_block["simp_reps"]
        else:
            simp_reps = {
                k: v
                for k, v in simp_block.items()
                if k not in {"ok", "fileName", "error", "partial", "partial_missing"}
            } or None

    # 2D section (.sec): Toolkit 0.5.0 domains.sketch. Other domains answer ok:false
    # ("does not apply to a SECTION"), which _ok_domain already treats as absent.
    sketch = None
    sketch_block = _ok_domain(payload, "sketch")
    if sketch_block:
        nested = sketch_block.get("sketch")
        source = nested if isinstance(nested, dict) else sketch_block
        # partial_missing is kept: it says which parts (entities / dimensions /
        # constraints) the Toolkit could not read, and why.
        sketch = {
            k: v
            for k, v in source.items()
            if k not in {"ok", "fileName", "error", "partial", "timings_ms"}
        } or None
    else:
        raw_domains = payload.get("domains")
        raw_sketch = raw_domains.get("sketch") if isinstance(raw_domains, dict) else None
        if isinstance(raw_sketch, dict) and raw_sketch.get("ok") is False:
            # Keep the Toolkit's reason so Details can say why there is no sketch data
            # (for example ProSectionEntityIdsGet=-2) instead of showing nothing.
            sketch = {
                "ok": False,
                "error": str(raw_sketch.get("error") or "sketch not available")[:300],
            }

    # Nested ai_snapshot so Ask AI / postAiSnapshotFromGather work without Creo.JS.
    identity_ai = dict(identity)
    tip = str(identity_ai.get("file_name") or identity_ai.get("full_name") or "").strip()
    if tip:
        identity_ai.setdefault("filename", tip)
    ai_snapshot = {
        "schema_version": 1,
        "identity": identity_ai,
        "features": features or [],
        "dimensions": dimensions,
        "parameters": parameters or [],
        "materials": materials,
        "units": units,
        "mass": mass,
        "family_table": None,
        "bom": bom,
        "structure": structure,
        "simp_reps": simp_reps,
        "constraints": constraints,
        "relations": None,
        "capture": {"status": "ok", "errors": [], "source": "toolkit"},
    }
    return {
        "identity": identity,
        "parameters": parameters,
        "materials": materials,
        "dependencies": [],
        "bom": bom,
        "units": units,
        "mass": mass,
        "family_table": None,
        "features": features,
        "dimensions": dimensions,
        "structure": structure,
        "simp_reps": simp_reps,
        "constraints": constraints,
        "relations": None,
        "sketch": sketch,
        "ai_snapshot": ai_snapshot,
        "_pdm_source": "toolkit",
    }
