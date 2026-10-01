"""Normalize Creo.JS model Type / role into CreoPDM identity codes."""

from __future__ import annotations

from typing import Any

# Stored on version.identity_json as model_type / model_role.

_MODEL_TYPE_ALIASES: dict[str, str] = {
    "PART": "PART",
    "MDL_PART": "PART",
    "ASSEMBLY": "ASSEMBLY",
    "MDL_ASSEMBLY": "ASSEMBLY",
    "DRAWING": "DRAWING",
    "MDL_DRAWING": "DRAWING",
    "MFG": "MFG",
    "MDL_MFG": "MFG",
    "LAYOUT": "LAYOUT",
    "MDL_LAYOUT": "LAYOUT",
    "MDL_CE_SOLID": "LAYOUT",
    "FORMAT": "FORMAT",
    "DWG_FORMAT": "FORMAT",
    "MDL_DWG_FORMAT": "FORMAT",
    "REPORT": "REPORT",
    "MDL_REPORT": "REPORT",
    "DIAGRAM": "DIAGRAM",
    "MDL_DIAGRAM": "DIAGRAM",
    "MARKUP": "MARKUP",
    "MDL_MARKUP": "MARKUP",
    "SECTION": "SECTION",
    "2D_SECTION": "SECTION",
    "MDL_2D_SECTION": "SECTION",
}

_MODEL_ROLE_ALIASES: dict[str, str] = {
    "SOLID": "SOLID",
    "SHEETMETAL": "SHEETMETAL",
    "SHEET_METAL": "SHEETMETAL",
    "SKELETON": "SKELETON",
    "BULK": "BULK",
    "HARNESS": "HARNESS",
    "PIPE": "PIPE",
    "DESIGN": "DESIGN",
    "INTERCHANGE": "INTERCHANGE",
    "MOLD_LAYOUT": "MOLD_LAYOUT",
    "CONFIGURABLE_MODULE": "CONFIGURABLE_MODULE",
    "CABLING_DATA": "CABLING_DATA",
    "NC": "NC",
    "MOLD": "MOLD",
    "CAST": "CAST",
    "MFG": "MFG",
    "SHEETMETAL_MFG": "SHEETMETAL_MFG",
    "SHEET_METAL_MFG": "SHEETMETAL_MFG",
}


def normalize_creo_model_type(value: Any) -> str:
    """Return PART/ASSEMBLY/… or '' when unknown / unspecified."""
    if value is None:
        return ""
    raw = str(value).strip().upper().replace(" ", "_")
    if not raw or raw in {"MDL_UNSPECIFIED", "MODELTYPE_NIL", "NIL", "NONE"}:
        return ""
    if raw in _MODEL_TYPE_ALIASES:
        return _MODEL_TYPE_ALIASES[raw]
    if raw.startswith("MDL_"):
        return _MODEL_TYPE_ALIASES.get(raw[4:], "")
    return ""


def normalize_creo_model_role(value: Any) -> str:
    """Return SOLID/SHEETMETAL/… or '' when unknown."""
    if value is None:
        return ""
    raw = str(value).strip().upper().replace(" ", "_")
    if not raw:
        return ""
    return _MODEL_ROLE_ALIASES.get(raw, "")


def normalize_creo_identity(identity: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize model_type / model_role keys on an identity dict (in place + return)."""
    if not isinstance(identity, dict):
        return identity
    identity["model_type"] = normalize_creo_model_type(identity.get("model_type"))
    identity["model_role"] = normalize_creo_model_role(identity.get("model_role"))
    return identity
