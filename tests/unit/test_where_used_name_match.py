"""Where Used must not treat bare name stems as assembly membership."""

from __future__ import annotations

from pathlib import Path

from creopdm.utils.cad_name_matcher import CadNameMatcher
from creopdm.utils.creo_dependencies import logical_name_in_model, model_references_filename


def test_matcher_without_stems_ignores_bare_part_number():
    """``1003573`` in an unrelated asm must not mean it uses ``1003573.asm``."""
    matcher = CadNameMatcher(
        ["1003573.asm", "other.prt", "frame.asm"],
        include_stems=False,
    )
    found = matcher.find(b"header notes mention 1003573 in a parameter footer")
    assert "1003573.asm" not in found
    assert matcher.find(b"assembly member 1003573.asm ok") == {"1003573.asm"}


def test_matcher_with_stems_still_finds_extensionless_for_open():
    matcher = CadNameMatcher(["pin.prt", "Bracket.ASM"], include_stems=True)
    found = matcher.find(b".... pin.prt .... bracket ....")
    assert "pin.prt" in found
    assert "bracket.asm" in found


def test_logical_name_in_model_requires_extension(tmp_path: Path):
    asm = tmp_path / "parent.asm"
    asm.write_bytes(b"noise 1003573 more noise")
    assert logical_name_in_model(asm, "1003573.asm") is False
    assert model_references_filename(asm, "1003573.asm") is False
    asm.write_bytes(b"member 1003573.asm here")
    assert logical_name_in_model(asm, "1003573.asm") is True
    assert model_references_filename(asm, "1003573.asm") is True


def test_rebuild_uses_extension_only_matcher():
    text = Path("src/creopdm/services/metadata_service.py").read_text(encoding="utf-8")
    assert "CadNameMatcher(candidate_names, include_stems=False)" in text
    assert "stem-only false" in text
