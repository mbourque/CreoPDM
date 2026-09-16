from creopdm.constants import DEFAULT_TYPE_LABELS, ObjectType
from creopdm.utils.classify import (
    classify_filename,
    default_folder_for,
    display_type_label,
    is_creo_openable,
    is_extra_cad,
    unique_type_labels,
)


def test_classify_known_extensions():
    assert classify_filename("shaft.prt") == ObjectType.CREO_PART
    assert classify_filename("robot.asm.4") == ObjectType.CREO_ASSEMBLY
    assert classify_filename("layout.drw") == ObjectType.CREO_DRAWING
    assert classify_filename("export.step") == ObjectType.CAD
    assert classify_filename("export.step", extra_cad_extensions=[], model_extensions=[]) == ObjectType.STEP
    assert classify_filename("spec.pdf") == ObjectType.PDF
    assert classify_filename("notes.docx") == ObjectType.DOCUMENT
    assert classify_filename("bom.xlsx") == ObjectType.SPREADSHEET
    assert classify_filename("photo.png") == ObjectType.IMAGE
    assert classify_filename("readme.txt") == ObjectType.TEXT
    assert classify_filename("index.html") == ObjectType.DOCUMENT
    assert classify_filename("site.css") == ObjectType.DOCUMENT
    assert classify_filename("app.js") == ObjectType.DOCUMENT
    assert classify_filename("app.ts") == ObjectType.DOCUMENT
    assert classify_filename("board.eda") == ObjectType.CAD
    assert classify_filename("calc.mcdx") == ObjectType.DOCUMENT
    assert classify_filename("duct.spro") == ObjectType.CAD


def test_classify_unknown_is_other():
    assert classify_filename("weird.xyz") == ObjectType.OTHER


def test_default_extra_cad_extensions():
    assert classify_filename("outline.dxf") == ObjectType.CAD
    assert classify_filename("toolpath.ncl") == ObjectType.CAD
    assert classify_filename("session.log") == ObjectType.CAD
    assert classify_filename("params.xml") == ObjectType.CAD
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
    assert classify_filename("preview.mtl") == ObjectType.CAD
    assert classify_filename("preview.mtl.1") == ObjectType.CAD
    assert classify_filename("imported.sldprt") == ObjectType.CAD
    assert classify_filename("body.CATPart") == ObjectType.CAD
    assert classify_filename("cutter.tmu") == ObjectType.CAD
    assert classify_filename("cutter.tmu.2") == ObjectType.CAD
    assert classify_filename("preview.pvz") == ObjectType.CAD
    assert classify_filename("preview.pvz.3") == ObjectType.CAD
    assert classify_filename("preview.3.pvz") == ObjectType.CAD
    assert classify_filename("session.tmz") == ObjectType.CAD
    assert classify_filename("view.ol") == ObjectType.CAD
    assert classify_filename("world.wrl") == ObjectType.CAD
    assert classify_filename("board.idx") == ObjectType.CAD
    assert classify_filename("print.3mf") == ObjectType.CAD
    assert classify_filename("board.eda") == ObjectType.CAD
    assert classify_filename("duct.spro") == ObjectType.CAD
    assert default_folder_for(ObjectType.CAD) == "CAD"
    assert default_folder_for(ObjectType.CREO_MANUFACTURING) == "CAD"


def test_extra_cad_extensions_override():
    assert classify_filename("notes.xyz", [".xyz"]) == ObjectType.CAD
    assert classify_filename("toolpath.ncl", extra_cad_extensions=[], model_extensions=[]) == ObjectType.OTHER
    assert classify_filename("shaft.prt", [".prt"]) == ObjectType.CREO_PART


def test_creo_openable_models():
    assert is_creo_openable("shaft.prt")
    assert is_creo_openable("outline.dxf.4")
    assert is_creo_openable("body.CATPart")
    assert is_creo_openable("cutter.tmu.2")
    assert is_creo_openable("preview.pvz.3")
    assert is_creo_openable("preview.3.pvz")
    assert is_creo_openable("session.tmz")
    assert is_creo_openable("world.wrl")
    assert is_creo_openable("board.idx")
    assert is_creo_openable("print.3mf")
    assert not is_creo_openable("setup.inf")
    assert not is_creo_openable("preview.mtl")
    assert not is_creo_openable("rough.ncl")
    assert not is_creo_openable("session.log")
    assert not is_creo_openable("notes.pdf")
    assert is_extra_cad("setup.inf")
    assert is_extra_cad("preview.mtl.1")
    assert is_extra_cad("1-inch.xpr")
    assert is_extra_cad("board.eda")
    assert is_extra_cad("duct.spro")
    assert not is_extra_cad("rough.ncl")
    assert not is_extra_cad("session.log")
    assert not is_extra_cad("shaft.prt")
    assert not is_extra_cad("world.wrl")
    assert not is_extra_cad("notes.pdf")
    assert not is_extra_cad("calc.mcdx")
    assert not is_creo_openable("board.eda")
    assert not is_creo_openable("duct.spro")


def test_default_folders():
    assert default_folder_for(ObjectType.CREO_PART) == "CAD"
    assert default_folder_for(ObjectType.PDF) == "Documents"
    assert default_folder_for(ObjectType.STEP) == "Exports"


def test_display_type_label_defaults_and_overrides():
    assert display_type_label("shaft.prt", "CREO_PART") == "Creo Part"
    assert display_type_label("shaft.prt", "CREO_PART", []) == "Creo Part"
    labels = [{"extension": ".prt", "label": "Part file"}]
    assert display_type_label("shaft.prt", "CREO_PART", labels) == "Part file"
    assert display_type_label("shaft.prt.3", "CREO_PART", labels) == "Part file"
    assert display_type_label("shaft.3.prt", "CREO_PART", labels) == "Part file"
    assert display_type_label("robot.asm", "CREO_ASSEMBLY", labels) == "Creo Assembly"
    assert unique_type_labels(
        [{"extension": "prt", "label": "A"}, {"extension": ".prt", "label": "B"}]
    ) == [{"extension": ".prt", "label": "B"}]
    assert unique_type_labels([{"extension": ".prt", "label": ""}]) == []
    variants = [{"extension": ".stp, .step", "label": "STEP Model"}]
    assert unique_type_labels(variants) == [{"extension": ".stp, .step", "label": "STEP Model"}]
    assert unique_type_labels([{"extension": ".step, .stp", "label": "STEP Model"}]) == [
        {"extension": ".step, .stp", "label": "STEP Model"}
    ]
    assert display_type_label("body.stp", "STEP", variants) == "STEP Model"
    assert display_type_label("body.step", "STEP", variants) == "STEP Model"
    assert display_type_label("body.stp.2", "STEP", variants) == "STEP Model"
    named = [{"extension": "reviewref.inf", "label": "Reference Info"}, {"extension": ".inf", "label": "Info"}]
    assert unique_type_labels(named) == [
        {"extension": "reviewref.inf", "label": "Reference Info"},
        {"extension": ".inf", "label": "Info"},
    ]
    assert display_type_label("reviewref.inf", "CAD", named) == "Reference Info"
    assert display_type_label("ReviewRef.INF", "CAD", named) == "Reference Info"
    assert display_type_label("reviewref.inf.1", "CAD", named) == "Reference Info"
    assert display_type_label("setup.inf", "CAD", named) == "Info"
    assert display_type_label("cut.mrd", "CAD", [{"extension": ".mrd", "label": "Material Removal Data"}]) == (
        "Material Removal Data"
    )
    xml = [
        {"extension": ".xml", "label": "XML File"},
        {"extension": "mw_settings.xml", "label": "Module Works Settings"},
    ]
    assert display_type_label("mw_settings.xml", "CAD", xml) == "Module Works Settings"
    assert display_type_label("MW_SETTINGS.XML", "CAD", xml) == "Module Works Settings"
    assert display_type_label("mw_settings.xml.1", "CAD", xml) == "Module Works Settings"
    assert display_type_label("params.xml", "CAD", xml) == "XML File"
    logs = [
        {"extension": ".log", "label": "Log file"},
        {"extension": "mc_error.log", "label": "ModelCHECK Error Log"},
    ]
    assert display_type_label("mc_error.log", "CAD", logs) == "ModelCHECK Error Log"
    assert display_type_label("mc_error.log.1", "CAD", logs) == "ModelCHECK Error Log"
    assert display_type_label("session.log", "CAD", logs) == "Log file"
    defaults = unique_type_labels(DEFAULT_TYPE_LABELS)
    assert display_type_label("index.html", "DOCUMENT", defaults) == "Webpage"
    assert display_type_label("site.css", "DOCUMENT", defaults) == "Stylesheet"
    assert display_type_label("app.js", "DOCUMENT", defaults) == "JavaScript"
    assert display_type_label("widget.tsx", "DOCUMENT", defaults) == "JavaScript"
    assert display_type_label("theme.scss", "DOCUMENT", defaults) == "Stylesheet"
    assert display_type_label("board.eda", "CAD", defaults) == "ECAD data"
    assert display_type_label("calc.mcdx", "DOCUMENT", defaults) == "Mathcad"
    assert display_type_label("duct.spro", "CAD", defaults) == "Creo Flow Analysis"
