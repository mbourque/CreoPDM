from creopdm.constants import ObjectType
from creopdm.utils.classify import classify_filename, default_folder_for


def test_classify_known_extensions():
    assert classify_filename("shaft.prt") == ObjectType.CREO_PART
    assert classify_filename("robot.asm.4") == ObjectType.CREO_ASSEMBLY
    assert classify_filename("layout.drw") == ObjectType.CREO_DRAWING
    assert classify_filename("export.step") == ObjectType.CAD
    assert classify_filename("export.step", []) == ObjectType.STEP
    assert classify_filename("spec.pdf") == ObjectType.PDF
    assert classify_filename("notes.docx") == ObjectType.DOCUMENT
    assert classify_filename("bom.xlsx") == ObjectType.SPREADSHEET
    assert classify_filename("photo.png") == ObjectType.IMAGE
    assert classify_filename("readme.txt") == ObjectType.TEXT


def test_classify_unknown_is_other():
    assert classify_filename("weird.xyz") == ObjectType.OTHER


def test_default_extra_cad_extensions():
    assert classify_filename("outline.dxf") == ObjectType.CAD
    assert classify_filename("toolpath.ncl") == ObjectType.CAD
    assert classify_filename("cycle.tph") == ObjectType.CAD
    assert classify_filename("setup.inf") == ObjectType.CAD
    assert classify_filename("setup.inf.1") == ObjectType.CAD
    assert classify_filename("outline.dxf.4") == ObjectType.CAD
    assert classify_filename("stock.igs") == ObjectType.CAD
    assert classify_filename("stock.igs.2") == ObjectType.CAD
    assert classify_filename("params.m_p") == ObjectType.CAD
    assert classify_filename("params.m_p.1") == ObjectType.CAD
    assert classify_filename("asm.bom") == ObjectType.CAD
    assert classify_filename("format.frm.2") == ObjectType.CAD
    assert classify_filename("sheet.tbl.1") == ObjectType.CAD
    assert classify_filename("process.mfg.3") == ObjectType.CREO_MANUFACTURING
    assert classify_filename("op10.bin") == ObjectType.CAD
    assert classify_filename("stock.stk") == ObjectType.CAD
    assert classify_filename("cnc-part.mrd.1") == ObjectType.CAD
    assert classify_filename("150-inch.xpr") == ObjectType.CAD
    assert default_folder_for(ObjectType.CAD) == "CAD"
    assert default_folder_for(ObjectType.CREO_MANUFACTURING) == "CAD"


def test_extra_cad_extensions_override():
    assert classify_filename("notes.xyz", [".xyz"]) == ObjectType.CAD
    assert classify_filename("outline.dxf", []) == ObjectType.OTHER
    assert classify_filename("shaft.prt", [".prt"]) == ObjectType.CREO_PART


def test_default_folders():
    assert default_folder_for(ObjectType.CREO_PART) == "CAD"
    assert default_folder_for(ObjectType.PDF) == "Documents"
    assert default_folder_for(ObjectType.STEP) == "Exports"
