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
