from creopdm.utils.cad_name_matcher import CadNameMatcher
from creopdm.utils.creo_companions import names_referenced_in_model


def test_cad_name_matcher_finds_logical_and_stem():
    matcher = CadNameMatcher(["pin.prt", "Bracket.ASM", "other.prt"])
    found = matcher.find(b".... pin.prt .... bracket ....")
    assert "pin.prt" in found
    assert "bracket.asm" in found
    assert "other.prt" not in found


def test_names_referenced_uses_matcher_for_large_candidate_sets(tmp_path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"header PIN.PRT footer")
    candidates = [f"part{i}.prt" for i in range(80)] + ["pin.prt"]
    found = names_referenced_in_model(asm, candidates)
    assert "pin.prt" in {item.lower() for item in found}
    assert "part0.prt" not in {item.lower() for item in found}
