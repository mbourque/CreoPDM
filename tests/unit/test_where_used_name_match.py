"""Where Used uses bounded stems; glued substrings must not become members."""

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


def test_matcher_requires_name_boundaries_for_where_used():
    """Regression: at311912.asm must not claim 844j.asm from a glued/noisy hit."""
    matcher = CadNameMatcher(
        ["844j.asm", "14m7303.prt", "at311912.asm"],
        include_stems=True,
        require_boundaries=True,
        min_stem_len=4,
    )
    parts_only = (
        b"\x00".join(
            [
                b"14m7303.prt",
                b"r44302_3.prt",
                b"t74416.prt",
                b"24m7027.prt",
                b"x844j.asm",  # glued prefix — not a real member token
                b"844j.asmx",  # glued suffix
                b"x844j",  # glued bare stem
            ]
        )
    )
    assert "844j.asm" not in matcher.find(parts_only)
    assert "14m7303.prt" in matcher.find(parts_only)
    assert matcher.find(b"\x00844j.asm\x00") == {"844j.asm"}
    # Creo component tables often store the bare name with null boundaries.
    assert matcher.find(b"\x00844j\x00") == {"844j.asm"}


def test_rebuild_uses_bounded_unique_stems_for_creo_component_names():
    text = Path("src/creopdm/services/metadata_service.py").read_text(encoding="utf-8")
    assert "include_stems=True" in text
    assert "require_boundaries=True" in text
    assert "min_stem_len=4" in text
    assert "unique_stems_only=True" in text


def test_matcher_prefers_asm_when_part_and_asm_share_stem():
    matcher = CadNameMatcher(
        ["shaft.prt", "shaft.asm", "pin.prt"],
        include_stems=True,
        require_boundaries=True,
        unique_stems_only=True,
    )
    # Bare "shaft" → assembly (Top Level needs sub-asm edges).
    assert matcher.find(b"\x00shaft\x00") == {"shaft.asm"}
    assert matcher.find(b"\x00pin\x00") == {"pin.prt"}
    assert matcher.find(b"\x00shaft.prt\x00") == {"shaft.prt"}



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
    asm.write_bytes(b"glued x1003573.asm end")
    assert logical_name_in_model(asm, "1003573.asm") is False


def test_rebuild_clears_membership_edges_before_reindex():
    text = Path("src/creopdm/services/metadata_service.py").read_text(encoding="utf-8")
    assert "Cleared ASSEMBLY_MEMBER/DRAWING_MODEL edges" in text
