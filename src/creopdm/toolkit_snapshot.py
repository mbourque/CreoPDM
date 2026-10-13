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
    if name.endswith(".mfg"):
        return "identity,parameters,mfg,units"
    if name.endswith(".drw"):
        return "identity,parameters,drawing,units"
    if name.endswith(".asm"):
        return "identity,parameters,features,structure,constraints,units"
    if name.endswith(".prt"):
        return "identity,parameters,features,materials,mass,units"
    return "identity,parameters,features,units"


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


def normalize_toolkit_structure_row(row: dict[str, Any]) -> dict[str, Any]:
    """Align Toolkit structure rows with Creo.JS Structure (tip name + PART/ASSEMBLY).

    CreoPDM drops COMPONENT rows whose name is not a CAD tip (datums / CSYS noise).
    Toolkit often emits type COMPONENT with ``shaft.prt`` — promote those to PART/ASSEMBLY
    so the Details Structure tab is not empty after filter_assembly_structure_rows.

    Skeleton tips are still ``*.prt``; never overwrite Toolkit ``SKELETON`` /
    ``is_skeleton`` with PART from the extension alone.
    """
    out = dict(row)
    name = _structure_row_name(out)
    typ = str(out.get("type") or "").strip().upper()
    role = str(out.get("role") or "").strip().upper()
    sub = str(out.get("subtype") or out.get("subType") or out.get("model_type") or "").strip().upper()
    lower = name.lower()
    skeleton = _structure_row_is_skeleton(out, typ, sub)

    if _CAD_STRUCTURE_TIP_RE.search(lower):
        if re.search(r"\.asm(\.\d+)?$", lower):
            typ = "ASSEMBLY"
        elif re.search(r"\.mfg(\.\d+)?$", lower):
            typ = "MFG"
        elif re.search(r"\.prt(\.\d+)?$", lower):
            # Keep Toolkit skeleton typing (type / subtype / is_skeleton).
            if skeleton or typ == "SKELETON":
                typ = "SKELETON"
                if not sub:
                    sub = "SKELETON"
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
    return out


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

    # Nested ai_snapshot so Ask AI / postAiSnapshotFromGather work without Creo.JS.
    identity_ai = dict(identity)
    tip = str(identity_ai.get("file_name") or identity_ai.get("full_name") or "").strip()
    if tip:
        identity_ai.setdefault("filename", tip)
    ai_snapshot = {
        "schema_version": 1,
        "identity": identity_ai,
        "features": features or [],
        "dimensions": [],
        "parameters": parameters or [],
        "materials": materials,
        "units": units,
        "mass": mass,
        "family_table": None,
        "bom": None,
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
        "bom": None,
        "units": units,
        "mass": mass,
        "family_table": None,
        "features": features,
        "structure": structure,
        "simp_reps": simp_reps,
        "constraints": constraints,
        "relations": None,
        "ai_snapshot": ai_snapshot,
        "_pdm_source": "toolkit",
    }
