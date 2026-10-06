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
    name = str(filename or "").strip().lower().replace("\\", "/")
    if not name:
        return False
    base = name.rsplit("/", 1)[-1]
    # Creo versioned tips: layout.prt.2
    if ".prt." in base:
        return True
    return base.endswith(".prt")


def _filename_looks_like_assembly(filename: Any) -> bool:
    name = str(filename or "").strip().lower().replace("\\", "/")
    if not name:
        return False
    base = name.rsplit("/", 1)[-1]
    if ".asm." in base:
        return True
    return base.endswith(".asm")


def normalize_creo_identity(identity: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize model_type / model_role keys on an identity dict (in place + return)."""
    if not isinstance(identity, dict):
        return identity
    identity["model_type"] = normalize_creo_model_type(identity.get("model_type"))
    identity["model_role"] = normalize_creo_model_role(identity.get("model_role"))
    # Skeleton subtype is parts only — never keep it on assemblies.
    if identity.get("model_role") == "SKELETON":
        mtype = str(identity.get("model_type") or "")
        fname = identity.get("file_name") or identity.get("filename") or ""
        if mtype == "ASSEMBLY" or _filename_looks_like_assembly(fname):
            identity["model_role"] = ""
        elif _filename_looks_like_part(fname):
            # Creo may report skeleton/concept as LAYOUT; store as PART + SKELETON.
            if mtype in ("", "LAYOUT"):
                identity["model_type"] = "PART"
        elif mtype not in ("PART", ""):
            identity["model_role"] = ""
        elif mtype == "" and not _filename_looks_like_part(fname):
            identity["model_role"] = ""
    return identity


def version_has_creo_metadata(version: Any) -> bool:
    """True when a version row has stored Creo identity or materials from Collect."""
    if version is None:
        return False
    identity = getattr(version, "identity_json", None)
    if identity is not None and str(identity).strip() not in ("", "null", "{}"):
        return True
    materials = getattr(version, "materials_json", None)
    if materials is not None and str(materials).strip() not in ("", "null", "{}"):
        return True
    return False


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
    Skeleton role is parts-only (assemblies fall through to model_type).
    """
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    # Apply the same part-only skeleton rule as save-time normalize.
    normalize_creo_identity(data)
    role = normalize_creo_model_role(data.get("model_role"))
    if role in _FILES_LIST_ROLE_LABELS:
        return role
    return normalize_creo_model_type(data.get("model_type"))
