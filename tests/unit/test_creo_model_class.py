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
    assert normalize_creo_model_role("MFG") == "MFG"
    assert normalize_creo_model_role("nope") == ""


def test_normalize_creo_identity_mutates_dict():
    identity = {"model_type": "MDL_PART", "model_role": "sheet metal", "common_name": "Pin"}
    out = normalize_creo_identity(identity)
    assert out is identity
    assert identity["model_type"] == "PART"
    assert identity["model_role"] == "SHEETMETAL"
    assert identity["common_name"] == "Pin"


def test_version_has_creo_metadata():
    from types import SimpleNamespace

    from creopdm.utils.creo_model_class import version_has_creo_metadata

    assert version_has_creo_metadata(None) is False
    assert version_has_creo_metadata(SimpleNamespace(identity_json=None)) is False
    assert (
        version_has_creo_metadata(
            SimpleNamespace(identity_json='{"model_type":"PART"}', materials_json=None)
        )
        is True
    )
    assert (
        version_has_creo_metadata(
            SimpleNamespace(identity_json=None, materials_json='{"current":"STEEL"}')
        )
        is True
    )


def test_skeleton_role_only_on_parts():
    asm = {"model_type": "ASSEMBLY", "model_role": "SKELETON", "file_name": "top.asm"}
    normalize_creo_identity(asm)
    assert asm["model_type"] == "ASSEMBLY"
    assert asm["model_role"] == ""

    named_asm = {"model_type": "", "model_role": "SKELETON", "file_name": "layout.asm.1"}
    normalize_creo_identity(named_asm)
    assert named_asm["model_role"] == ""

    part = {"model_type": "PART", "model_role": "SKELETON", "file_name": "layout.prt"}
    normalize_creo_identity(part)
    assert part["model_role"] == "SKELETON"

    inferred = {"model_type": "", "model_role": "SKELETON", "file_name": "layout.prt.2"}
    normalize_creo_identity(inferred)
    assert inferred["model_type"] == "PART"
    assert inferred["model_role"] == "SKELETON"

    # Creo may report a skeleton/concept as LAYOUT; it is still a .prt skeleton part.
    layout_prt = {"model_type": "LAYOUT", "model_role": "SKELETON", "file_name": "layout.prt"}
    normalize_creo_identity(layout_prt)
    assert layout_prt["model_type"] == "PART"
    assert layout_prt["model_role"] == "SKELETON"


def test_model_type_from_identity_json():
    from creopdm.utils.creo_model_class import model_type_from_identity_json
    from creopdm.utils.classify import resolve_type_icon

    assert model_type_from_identity_json(None) == ""
    assert model_type_from_identity_json("{") == ""
    assert model_type_from_identity_json('{"model_type":"MDL_MFG"}') == "MFG"
    assert model_type_from_identity_json('{"model_type":"ASSEMBLY"}') == "ASSEMBLY"
    assert resolve_type_icon(type_label="MFG") == "mfg.png"
    assert resolve_type_icon(type_label="Manufacturing Model") == "mfg.png"


def test_files_list_type_prefers_distinctive_role():
    from creopdm.utils.classify import resolve_type_icon
    from creopdm.utils.creo_model_class import files_list_type_from_identity_json

    assert (
        files_list_type_from_identity_json(
            '{"model_type":"PART","model_role":"SHEETMETAL"}'
        )
        == "SHEETMETAL"
    )
    assert (
        files_list_type_from_identity_json('{"model_type":"PART","model_role":"SOLID"}')
        == "PART"
    )
    assert (
        files_list_type_from_identity_json(
            '{"model_type":"PART","model_role":"SKELETON"}'
        )
        == "SKELETON"
    )
    assert (
        files_list_type_from_identity_json('{"model_type":"MFG","model_role":"MFG"}')
        == "MFG"
    )
    assert files_list_type_from_identity_json('{"model_type":"ASSEMBLY"}') == "ASSEMBLY"
    assert (
        files_list_type_from_identity_json(
            '{"model_type":"ASSEMBLY","model_role":"SKELETON"}'
        )
        == "ASSEMBLY"
    )
    assert resolve_type_icon(type_label="SHEETMETAL") == "part.png"
