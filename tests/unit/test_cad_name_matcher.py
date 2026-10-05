from creopdm.utils.cad_name_matcher import CadNameMatcher
from creopdm.utils.creo_dependencies import names_referenced_in_model


def test_cad_name_matcher_finds_logical_and_stem():
    matcher = CadNameMatcher(["pin.prt", "Bracket.ASM", "other.prt"], include_stems=True)
    found = matcher.find(b".... pin.prt .... bracket ....")
    assert "pin.prt" in found
    assert "bracket.asm" in found
    assert "other.prt" not in found


def test_cad_name_matcher_extension_only_skips_bare_stem():
    matcher = CadNameMatcher(["pin.prt", "Bracket.ASM"], include_stems=False)
    found = matcher.find(b".... pin.prt .... bracket ....")
    assert "pin.prt" in found
    assert "bracket.asm" not in found


def test_cad_name_matcher_extension_only_requires_boundaries():
    matcher = CadNameMatcher(["844j.asm"], include_stems=False)
    assert "844j.asm" not in matcher.find(b"xx844j.asm yy")
    assert "844j.asm" in matcher.find(b"xx 844j.asm yy")


def test_names_referenced_uses_matcher_for_large_candidate_sets(tmp_path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"header PIN.PRT footer")
    candidates = [f"part{i}.prt" for i in range(80)] + ["pin.prt"]
    found = names_referenced_in_model(asm, candidates)
    assert "pin.prt" in {item.lower() for item in found}
    assert "part0.prt" not in {item.lower() for item in found}
