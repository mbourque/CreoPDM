from creopdm.constants import ObjectType
from creopdm.utils.classify import classify_filename, default_folder_for


def test_classify_known_extensions():
    assert classify_filename("shaft.prt") == ObjectType.CREO_PART
    assert classify_filename("robot.asm.4") == ObjectType.CREO_ASSEMBLY
    assert classify_filename("layout.drw") == ObjectType.CREO_DRAWING
    assert classify_filename("export.step") == ObjectType.STEP
    assert classify_filename("spec.pdf") == ObjectType.PDF
    assert classify_filename("notes.docx") == ObjectType.DOCUMENT
    assert classify_filename("bom.xlsx") == ObjectType.SPREADSHEET
    assert classify_filename("photo.png") == ObjectType.IMAGE
    assert classify_filename("readme.txt") == ObjectType.TEXT


def test_classify_unknown_is_other():
    assert classify_filename("weird.xyz") == ObjectType.OTHER


def test_default_folders():
    assert default_folder_for(ObjectType.CREO_PART) == "CAD"
    assert default_folder_for(ObjectType.PDF) == "Documents"
    assert default_folder_for(ObjectType.STEP) == "Exports"
