"""Normalize Creo.JS model Type / role into CreoPDM identity codes."""

from __future__ import annotations

import json
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


def _filename_looks_like_part(filename: Any) -> bool:
    from creopdm.creo.file_manager import CreoFileManager

    logical = CreoFileManager.logical_filename(str(filename or "")).lower()
    return logical.endswith(".prt")


def _filename_looks_like_assembly(filename: Any) -> bool:
    from creopdm.creo.file_manager import CreoFileManager

    logical = CreoFileManager.logical_filename(str(filename or "")).lower()
    return logical.endswith(".asm")


def normalize_creo_identity(identity: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize model_type / model_role keys on an identity dict (in place + return)."""
    if not isinstance(identity, dict):
        return identity
    identity["model_type"] = normalize_creo_model_type(identity.get("model_type"))
    identity["model_role"] = normalize_creo_model_role(identity.get("model_role"))
    # Creo skeleton models are parts only — never keep SKELETON on an assembly.
    if identity["model_role"] == "SKELETON":
        kind = identity["model_type"]
        filename = identity.get("file_name") or identity.get("full_name") or ""
        if kind == "ASSEMBLY" or _filename_looks_like_assembly(filename):
            identity["model_role"] = ""
        elif kind and kind != "PART":
            identity["model_role"] = ""
        elif not kind and _filename_looks_like_part(filename):
            identity["model_type"] = "PART"
    return identity


def model_type_from_identity_json(raw: str | None) -> str:
    """Return normalized model_type from a version.identity_json blob, or ''."""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return normalize_creo_model_type(data.get("model_type"))


def version_has_creo_metadata(version: Any | None) -> bool:
    """True when this version already has stored Creo metadata (Collect should skip)."""
    if version is None:
        return False
    if model_type_from_identity_json(getattr(version, "identity_json", None)):
        return True
    for attr in (
        "materials_json",
        "bom_json",
        "units_json",
        "mass_json",
        "family_table_json",
        "features_json",
    ):
        if getattr(version, attr, None):
            return True
    return False


# Roles that are useful as the Files list Type column (not generic SOLID).
_FILES_LIST_ROLE_LABELS: frozenset[str] = frozenset(
    {
        "SHEETMETAL",
        "SKELETON",
        "BULK",
        "HARNESS",
        "PIPE",
        "MFG",
        "SHEETMETAL_MFG",
        "NC",
        "MOLD",
        "CAST",
        "INTERCHANGE",
        "MOLD_LAYOUT",
        "CONFIGURABLE_MODULE",
        "CABLING_DATA",
    }
)


def files_list_type_from_identity_json(raw: str | None) -> str:
    """
    Label for the Files list Type column from collected Creo identity.

    Prefer a distinctive model_role (SHEETMETAL, SKELETON, MFG, …) over a generic
    model_type (PART). SOLID is never shown — fall through to PART/ASSEMBLY/….
    """
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    identity = dict(data)
    normalize_creo_identity(identity)
    role = identity.get("model_role") or ""
    if role in _FILES_LIST_ROLE_LABELS:
        return role
    return identity.get("model_type") or ""
