"""A Collect that leaves a file without metadata says so instead of staying silent."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module() -> str:
    return (ROOT / "src" / "creopdm" / "static" / "js" / "creo_workspace.js").read_text(encoding="utf-8")


def test_files_that_got_no_metadata_are_named_to_the_user():
    script = _module()
    # saved ids are tracked per target, so a skipped / failed file is known at the end
    assert "const savedIds = new Set();" in script and "savedIds.add(target.uuid);" in script
    assert "noteCollectFailures(" in script and "targets.filter((target) => !savedIds.has(target.uuid))" in script
    body = script.split("function noteCollectFailures", 1)[1].split("async function pushCreoMetadataForItems", 1)[0]
    assert "Metadata was not collected for" in body and "Collect it again once that is fixed." in body
    # an Open (session lookup) and a disk read fail for different reasons
    assert "Creo did not report the model in its session." in body and "Creo could not read the file." in body
    # a drawing or assembly points at its missing models
    assert "needs the models it uses to be in the product" in body and "(drw|asm)" in body
    # the existing next-page notice keeps it alive across the reload that follows Add / Check in
    assert '"creopdmNotice"' in body and "toolbar-error" in body


def test_the_module_has_what_the_notice_needs():
    script = _module()
    assert "const showError = shell.showError;" in script and "const $ = shell.$;" in script
    shell = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "    $,\n" in shell.replace("\r\n", "\n") and "    showError,\n" in shell.replace("\r\n", "\n")


def test_no_stub_identity_is_saved_for_an_unreadable_file():
    """A stub identity would mark the file as collected and Collect all would then skip it for good."""
    script = _module()
    save = script.split("const identityName", 1)[1][:200]
    assert "if (!identityName) continue;" in save  # nothing is posted without a real identity name
    serializers = (ROOT / "src" / "creopdm" / "api" / "serializers.py").read_text(encoding="utf-8")
    assert "creo_metadata_captured" in serializers


def test_a_manual_collect_names_the_files_it_skipped_with_the_toolkit_reason():
    metadata = (ROOT / "src" / "creopdm" / "static" / "js" / "metadata.js").read_text(encoding="utf-8")
    assert "const failedFiles = [];" in metadata
    assert "failedFiles.push({ filename: target.filename, detail, newerRelease: Boolean(result.newerRelease) });" in metadata
    assert "if (failedFiles.length) await noteCollectFailures(failedFiles, false);" in metadata
    assert "const noteCollectFailures = shell.noteCollectFailures;" in metadata
    # harness (expected) skips and files left for Check In are not failures
    assert "expectedSkipped += 1;" in metadata and "leftLocal += 1;" in metadata
    script = _module()
    assert "mod.noteCollectFailures = noteCollectFailures;" in script
    assert 'target.detail)?.detail' in script  # the Toolkit's own reason, when a manual run has it
    app = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "async function noteCollectFailures(failed, fromOpen)" in app and "    noteCollectFailures,\n" in app.replace("\r\n", "\n")



def test_opening_a_file_in_a_released_product_does_not_try_to_capture_metadata():
    """Regression: Open in a Released product tried to save metadata, the server refused, and the page
    showed "Metadata was not collected ..." for a file the product is not allowed to change."""
    script = _module()
    body = script.split("async function captureCreoMetadataAfterOpen(result) {", 1)[1].split("async function rematerialize", 1)[0]
    assert "access.allows_edit_metadata === false" in body
    assert body.index("allows_edit_metadata") < body.index("pushCreoMetadataForItems(")


def test_opening_a_file_that_already_has_its_metadata_does_not_scan_it_again():
    script = _module()
    body = script.split("async function captureCreoMetadataAfterOpen(result) {", 1)[1].split("async function rematerialize", 1)[0]
    assert "object.creo_metadata_captured === true" in body and "if (!pending.length) return 0;" in body
    assert "pushCreoMetadataForItems(pending," in body


def test_a_bulk_subtype_makes_the_files_type_column_read_bulk():
    import json

    from creopdm.utils.creo_model_class import files_list_type_from_identity_json

    identity = json.dumps({"file_name": "1s0122.prt", "model_type": "PART", "subtype": "BULK"})
    assert files_list_type_from_identity_json(identity) == "BULK"
    # an explicit role still wins; an ordinary part stays PART
    assert files_list_type_from_identity_json(json.dumps({"model_type": "PART", "model_role": "BULK"})) == "BULK"
    assert files_list_type_from_identity_json(json.dumps({"model_type": "PART", "subtype": "SOLID"})) == "PART"
