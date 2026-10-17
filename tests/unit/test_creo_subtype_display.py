"""Overview "Subtype" row and Files Type column: Toolkit subtype + model_role → PROCESS."""

from creopdm.utils.creo_model_class import (
    creo_subtype_display,
    files_list_type_from_identity_json,
    normalize_creo_identity,
)


def test_process_assembly_reads_only_process_and_keeps_the_raw_subtype_out_of_sight():
    shown = creo_subtype_display(
        {"subtype": "ASM_PROCPLAN", "model_role": "PROCESS", "model_type": "ASSEMBLY"}
    )
    assert shown == {
        "label": "PROCESS",
        "subtype": "ASM_PROCPLAN",
        "model_role": "PROCESS",
        "raw": "ASM_PROCPLAN · PROCESS",
    }


def test_no_toolkit_subtype_means_fall_back_to_what_overview_showed_before():
    # Model not collected, or an older Collect without identity.subtype.
    assert creo_subtype_display(None) is None
    assert creo_subtype_display({}) is None
    assert creo_subtype_display({"model_role": "PROCESS"}) is None
    assert creo_subtype_display({"subtype": "   ", "model_role": "SHEETMETAL"}) is None


def test_without_a_role_the_row_reads_the_raw_subtype():
    shown = creo_subtype_display({"subtype": "ASM_PROCPLAN"})
    assert shown["label"] == "ASM_PROCPLAN"
    assert shown["raw"] == "ASM_PROCPLAN"
    same = creo_subtype_display({"subtype": "Sheetmetal", "model_role": "SHEETMETAL"})
    assert same["label"] == "SHEETMETAL"
    assert same["raw"] == "Sheetmetal"
    camel = creo_subtype_display({"subType": "ASM_PROCPLAN", "model_role": "PROCESS"})
    assert camel["label"] == "PROCESS"


def test_process_role_survives_normalize_so_the_raw_role_is_not_lost():
    # Regression: PROCESS was not a known role, so save/read normalized it to "".
    identity = normalize_creo_identity(
        {
            "file_name": "gorilla-cart-plan.asm",
            "model_type": "ASSEMBLY",
            "model_role": "PROCESS",
            "subtype": "ASM_PROCPLAN",
        }
    )
    assert identity["model_role"] == "PROCESS"
    assert identity["subtype"] == "ASM_PROCPLAN"
    assert normalize_creo_identity({"model_role": "NOT_A_ROLE"})["model_role"] == ""


def test_files_list_type_column_reads_process_for_a_process_assembly():
    # Regression: PROCESS was not a "distinctive" role, so the Type column said ASSEMBLY.
    process = '{"model_type":"ASSEMBLY","model_role":"PROCESS","subtype":"ASM_PROCPLAN"}'
    assert files_list_type_from_identity_json(process) == "PROCESS"
    # Ordinary assemblies and parts are unchanged.
    assert files_list_type_from_identity_json('{"model_type":"ASSEMBLY"}') == "ASSEMBLY"
    assert (
        files_list_type_from_identity_json('{"model_type":"PART","model_role":"SOLID"}') == "PART"
    )
