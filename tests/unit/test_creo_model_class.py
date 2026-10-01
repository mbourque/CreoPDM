"""Unit tests for Creo model_type / model_role normalization."""

from creopdm.utils.creo_model_class import (
    normalize_creo_identity,
    normalize_creo_model_role,
    normalize_creo_model_type,
)


def test_normalize_creo_model_type_aliases():
    assert normalize_creo_model_type("MDL_PART") == "PART"
    assert normalize_creo_model_type("part") == "PART"
    assert normalize_creo_model_type("MDL_ASSEMBLY") == "ASSEMBLY"
    assert normalize_creo_model_type("MDL_DWG_FORMAT") == "FORMAT"
    assert normalize_creo_model_type("MDL_2D_SECTION") == "SECTION"
    assert normalize_creo_model_type("MDL_CE_SOLID") == "LAYOUT"
    assert normalize_creo_model_type("MDL_UNSPECIFIED") == ""
    assert normalize_creo_model_type(None) == ""


def test_normalize_creo_model_role_aliases():
    assert normalize_creo_model_role("sheetmetal") == "SHEETMETAL"
    assert normalize_creo_model_role("SHEET_METAL") == "SHEETMETAL"
    assert normalize_creo_model_role("SKELETON") == "SKELETON"
    assert normalize_creo_model_role("SOLID") == "SOLID"
    assert normalize_creo_model_role("nope") == ""


def test_normalize_creo_identity_mutates_dict():
    identity = {"model_type": "MDL_PART", "model_role": "sheet metal", "common_name": "Pin"}
    out = normalize_creo_identity(identity)
    assert out is identity
    assert identity["model_type"] == "PART"
    assert identity["model_role"] == "SHEETMETAL"
    assert identity["common_name"] == "Pin"
