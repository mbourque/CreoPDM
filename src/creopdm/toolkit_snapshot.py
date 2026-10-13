"""Map CreoPDM Toolkit ``/collect`` JSON into a gatherModelMetadata-shaped snapshot.

Used by the local agent ``/toolkit/snapshot`` proxy so the browser can POST the
same ``CreoMetadataRequest`` body as Creo.JS gather. Probes / creo_inventory stay
untouched as the Creo.JS fallback.
"""

from __future__ import annotations

from typing import Any

DEFAULT_TOOLKIT_BASE_URL = "http://127.0.0.1:8767"


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


def map_toolkit_collect_to_snapshot(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a Creo.JS-gather-shaped snapshot, or None when identity is missing."""
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return None

    identity_block = _ok_domain(payload, "identity")
    identity: dict[str, Any] | None = None
    if identity_block and isinstance(identity_block.get("identity"), dict):
        identity = dict(identity_block["identity"])
    elif isinstance(payload.get("identity"), dict):
        identity = dict(payload["identity"])

    if not identity:
        return None
    file_name = str(identity.get("file_name") or identity.get("full_name") or "").strip()
    if not file_name:
        # Prefer collect/fileName when identity lacks file_name.
        tip = str(payload.get("fileName") or "").strip()
        if tip:
            identity = {**identity, "file_name": tip}
            file_name = tip
    if not file_name:
        return None

    parameters_block = _ok_domain(payload, "parameters")
    parameters = _list_field(parameters_block, "parameters") or []

    features = _list_field(_ok_domain(payload, "features"), "features")
    structure = _list_field(_ok_domain(payload, "structure"), "structure", "features", "components")

    drawing_block = _ok_domain(payload, "drawing")
    if drawing_block:
        draw_feats = _list_field(drawing_block, "features")
        if draw_feats is not None:
            features = draw_feats

    mfg_block = _ok_domain(payload, "mfg")
    if mfg_block:
        mfg_feats = _list_field(mfg_block, "features")
        if mfg_feats is not None:
            features = mfg_feats
        models = _list_field(mfg_block, "models")
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

    mass_block = _ok_domain(payload, "mass")
    mass = None
    if mass_block:
        if isinstance(mass_block.get("mass"), dict):
            mass = mass_block["mass"]
        else:
            mass = {
                k: v
                for k, v in mass_block.items()
                if k not in {"ok", "fileName", "error", "partial", "partial_missing"}
            } or None

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
        "_pdm_source": "toolkit",
    }
