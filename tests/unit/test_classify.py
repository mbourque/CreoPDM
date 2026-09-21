from creopdm.constants import DEFAULT_TYPE_LABELS, ObjectType
from creopdm.utils.classify import (
    classify_filename,
    default_folder_for,
    display_type_label,
    is_creo_js_openable,
    is_creo_openable,
    is_creo_view,
    is_extra_cad,
    matches_cad_models,
    matches_document,
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
    assert classify_filename("setup.rcp") == ObjectType.CAD
    assert classify_filename("cut.mbx") == ObjectType.CAD
    assert classify_filename("press.smt") == ObjectType.CAD
    assert classify_filename("site.sit") == ObjectType.CAD
    assert classify_filename("family.ptd") == ObjectType.CAD
    assert classify_filename("op10.lst") == ObjectType.CAD
    assert classify_filename("op10.ncl.tl1") == ObjectType.CAD
    assert classify_filename("slides.pptx") == ObjectType.DOCUMENT
    assert classify_filename("notes.odt") == ObjectType.DOCUMENT
    assert classify_filename("photo.gif") == ObjectType.IMAGE
    assert classify_filename("readme.md") == ObjectType.TEXT
    assert classify_filename("mail.msg") == ObjectType.DOCUMENT
    assert classify_filename("chart.vsdx") == ObjectType.DOCUMENT
    assert classify_filename("spec.rtf") == ObjectType.DOCUMENT
    assert classify_filename("art.psd") == ObjectType.IMAGE
    assert classify_filename("data.json") == ObjectType.TEXT
    assert classify_filename("custom.xyz", document_extensions=[".xyz"]) == ObjectType.DOCUMENT
    assert classify_filename("spec.pdf", extra_cad_extensions=[".pdf"]) == ObjectType.CAD


def test_classify_unknown_is_other():
    assert classify_filename("weird.xyz") == ObjectType.OTHER


def test_matches_cad_models_uses_logical_suffix():
    models = [".prt", ".asm", ".drw"]
    assert matches_cad_models("shaft.prt", models)
    assert matches_cad_models("shaft.prt.3", models)
    assert matches_cad_models("arm.asm", models, ".asm")
    assert matches_cad_models("sheet.drw.2", models)
    assert not matches_cad_models("notes.pdf", models)
    assert not matches_cad_models("cut.mfg", models)
    assert matches_cad_models("cut.mfg", [".mfg"])
    assert not matches_cad_models("shaft.prt", [])


def test_matches_document_uses_logical_suffix():
    docs = [".pdf", ".docx", ".odt"]
    assert matches_document("notes.pdf", docs)
    assert matches_document("notes.pdf.2", docs)
    assert classify_filename("notes.pdf.2") == ObjectType.PDF
    assert matches_document("spec.docx", docs, ".docx")
    assert matches_document("letter.odt", docs)
    assert not matches_document("shaft.prt", docs)
    assert not matches_document("notes.pdf", [])


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
    assert classify_filename("setup.rcp") == ObjectType.CAD
    assert classify_filename("setup.rcp.1") == ObjectType.CAD
    assert classify_filename("cut.mbx") == ObjectType.CAD
    assert classify_filename("press.smt") == ObjectType.CAD
    assert classify_filename("alias.ncd") == ObjectType.CAD
    assert classify_filename("check.nck") == ObjectType.CAD
    assert classify_filename("op10.lst") == ObjectType.CAD
    assert classify_filename("op10.lst.2") == ObjectType.CAD
    assert classify_filename("op10.ncl.tl1") == ObjectType.CAD
    assert classify_filename("OP10.NCL.TL12") == ObjectType.CAD
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
    assert not is_creo_openable("cutter.tmu.2")
    assert is_creo_openable("preview.pvz.3")
    assert is_creo_openable("preview.3.pvz")
    assert is_creo_view("preview.pvz")
    assert is_creo_view("preview.pvz.3")
    assert is_creo_view("preview.3.pvz")
    assert is_creo_view("session.pvs")
    assert is_creo_view("view.ol")
    assert is_creo_view("product.edz")
    assert not is_creo_view("shaft.prt")
    assert not is_creo_view("notes.pdf")
    assert not is_creo_openable("session.tmz")
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
    assert is_extra_cad("setup.rcp")
    assert is_extra_cad("setup.rcp.2")
    assert is_extra_cad("cut.mbx")
    assert is_extra_cad("cutter.tmu")
    assert is_extra_cad("cutter.tmu.2")
    assert is_extra_cad("session.tmz")
    assert not is_creo_openable("cutter.tmu")
    assert is_extra_cad("press.smt")
    assert is_extra_cad("family.ptd.1")
    assert is_extra_cad("prog.als")
    assert is_extra_cad("mill.mac")
    assert is_extra_cad("fast.xas")
    assert is_extra_cad("setup.dtl")
    assert is_extra_cad("cut.tpm")
    assert is_extra_cad("colors.map")
    assert not is_creo_openable("press.smt")
    assert not is_extra_cad("op10.lst")
    assert not is_extra_cad("op10.ncl.tl1")
    assert not is_extra_cad("rough.ncl")
    assert not is_extra_cad("session.log")
    assert not is_extra_cad("shaft.prt")
    assert not is_extra_cad("world.wrl")
    assert not is_extra_cad("notes.pdf")
    assert not is_extra_cad("calc.mcdx")
    assert not is_creo_openable("board.eda")
    assert not is_creo_openable("duct.spro")
    assert not is_creo_openable("setup.rcp")


def test_creo_js_skips_multicad_formats():
    assert is_creo_js_openable("shaft.prt")
    assert is_creo_js_openable("export.step")
    assert is_creo_js_openable("outline.dxf")
    assert not is_creo_js_openable("bolt_sw.SLDPRT")
    assert not is_creo_js_openable("body.CATPart")
    assert not is_creo_js_openable("block.ipt")
    assert not is_creo_js_openable("rough.ncl")


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
    assert display_type_label("setup.rcp", "CAD", defaults) == "Recipe/configuration"
    assert display_type_label("setup.rcp.1", "CAD", defaults) == "Recipe/configuration"
    assert display_type_label("cut.mbx", "CAD", defaults) == "Toolpath"
    assert display_type_label("setup.inf", "CAD", defaults) == "Information"
    assert display_type_label("reviewref.inf", "CAD", defaults) == "Reference Info"
    assert display_type_label("press.smt", "CAD", defaults) == "Punch Parameters"
    assert display_type_label("family.ptd.2", "CAD", defaults) == "Family Table"
    assert display_type_label("check.nck", "CAD", defaults) == "NC Check Image"
    assert display_type_label("alias.ncd", "CAD", defaults) == "CL Alias"
    assert display_type_label("sheet.plt", "CAD", defaults) == "Plot"
    assert display_type_label("op10.lst", "CAD", defaults) == "Post-list"
    assert display_type_label("op10.lst.2", "CAD", defaults) == "Post-list"
    assert unique_type_labels([{"extension": ".ncl.tl*", "label": "Intermediate CL File"}]) == [
        {"extension": ".ncl.tl*", "label": "Intermediate CL File"}
    ]
    assert display_type_label("op010.ncl.tl1", "OTHER", defaults) == "Intermediate CL File"
    assert display_type_label("op10.ncl.tl1", "CAD", defaults) == "Intermediate CL File"
    assert display_type_label("OP10.NCL.TL12", "CAD", defaults) == "Intermediate CL File"
    assert display_type_label("rough.ncl", "CAD", defaults) == "CL Data"
    assert display_type_label("notes.odt", "DOCUMENT", defaults) == "Word Document"
    assert display_type_label("chart.vsdx", "DOCUMENT", defaults) == "Visio Drawing"
    assert display_type_label("mail.msg", "DOCUMENT", defaults) == "Email"
    assert display_type_label("spec.xps", "PDF", defaults) == "XPS Document"
    assert display_type_label("config.yaml", "TEXT", defaults) == "YAML"
    assert display_type_label("art.psd", "IMAGE", defaults) == "Photoshop"
    assert display_type_label("asm.bom", "CAD", defaults) == "BOM"
    assert display_type_label("mass.m_p", "CAD", defaults) == "Mass Properties"
    assert display_type_label("view.wrl", "CAD", defaults) == "VRML"
    assert display_type_label("wiring.dgm", "CAD", defaults) == "Diagram"
    assert display_type_label("redline.mrk", "CAD", defaults) == "Markup"
    assert display_type_label("prog.als", "CAD", defaults) == "Assembly Program"
    assert display_type_label("old.ref", "CAD", defaults) == "Rename Reference"
    assert display_type_label("check.tst", "CAD", defaults) == "Verify Results"
    assert display_type_label("colors.map", "CAD", defaults) == "Color Map"
    assert display_type_label("setup.ers", "CAD", defaults) == "Setup Errors"
    assert display_type_label("diff.info", "CAD", defaults) == "Compare/Review Info"
    assert display_type_label("harness.cbl", "CAD", defaults) == "Cable Parameters"
    assert display_type_label("plug.con", "CAD", defaults) == "Connector Parameters"
    assert display_type_label("scene.lgh", "CAD", defaults) == "Lights"
    assert display_type_label("mill.mac", "CAD", defaults) == "Machine Data"
    assert display_type_label("mesh.bde", "CAD", defaults) == "Mesh Aspect Errors"
    assert display_type_label("mesh.bdi", "CAD", defaults) == "Mesh Jacobian Errors"
    assert display_type_label("mesh.bdm", "CAD", defaults) == "Mesh Mid-Ratio Errors"
    assert display_type_label("geom.ger", "CAD", defaults) == "Geometry Errors"
    assert display_type_label("part.pls", "CAD", defaults) == "Part Program"
    assert display_type_label("course.txa", "CAD", defaults) == "Training"
    assert display_type_label("trail.txt", "OTHER", defaults) == "Trail"
    assert display_type_label("trail.txt.5", "OTHER", defaults) == "Trail"
    assert display_type_label("index.idx", "CAD", defaults) == "Instance Accelerator"
    assert display_type_label("fast.xas", "CAD", defaults) == "Instance Accelerator"
    assert display_type_label("fast.xpr", "CAD", defaults) == "Instance Accelerator"
