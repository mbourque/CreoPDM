"""Central application identity and domain enumerations."""

from __future__ import annotations

from enum import StrEnum

APP_NAME = "CreoPDM"
APP_VERSION = "0.1.0"
APP_SCHEMA_VERSION = 1

DEFAULT_BRANCH = "main"
DEFAULT_REVISION = "A"
INITIAL_ITERATION = 1

PROJECT_MARKER_DIR = ".creopdm"
PROJECT_JSON_NAME = "project.json"
SCHEMA_VERSION_NAME = "schema_version"

STANDARD_PROJECT_FOLDERS = ("CAD", "Documents", "Exports", "References")


class ObjectType(StrEnum):
    CREO_PART = "CREO_PART"
    CREO_ASSEMBLY = "CREO_ASSEMBLY"
    CREO_DRAWING = "CREO_DRAWING"
    CREO_MANUFACTURING = "CREO_MANUFACTURING"
    CAD = "CAD"
    STEP = "STEP"
    PDF = "PDF"
    DOCUMENT = "DOCUMENT"
    SPREADSHEET = "SPREADSHEET"
    IMAGE = "IMAGE"
    TEXT = "TEXT"
    OTHER = "OTHER"


class LifecycleState(StrEnum):
    IN_WORK = "IN_WORK"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class CheckoutStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


class DependencyType(StrEnum):
    ASSEMBLY_MEMBER = "ASSEMBLY_MEMBER"
    DRAWING_MODEL = "DRAWING_MODEL"
    REFERENCE = "REFERENCE"
    SKELETON = "SKELETON"
    MERGE = "MERGE"
    UNKNOWN = "UNKNOWN"


class ActivityAction(StrEnum):
    PROJECT_CREATED = "PROJECT_CREATED"
    PROJECT_UPDATED = "PROJECT_UPDATED"
    OBJECT_ADDED = "OBJECT_ADDED"
    OBJECT_REMOVED = "OBJECT_REMOVED"
    WORKSPACE_CLEARED = "WORKSPACE_CLEARED"
    CHECKED_OUT = "CHECKED_OUT"
    CHECKOUT_CANCELLED = "CHECKOUT_CANCELLED"
    CHECKED_IN = "CHECKED_IN"
    VERSION_RESTORED = "VERSION_RESTORED"
    REMOTE_PUSH = "REMOTE_PUSH"
    REMOTE_PULL = "REMOTE_PULL"
    STATE_CHANGED = "STATE_CHANGED"
    ERROR = "ERROR"


class RemoteMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    LOCAL_WITH_REMOTE = "LOCAL_WITH_REMOTE"


CREO_FILE_EXTENSIONS = frozenset(
    {
        ".prt",
        ".asm",
        ".drw",
        ".mfg",
        ".frm",
        ".lay",
        ".sec",
        ".dgm",
        ".rep",
        ".mrk",
        ".int",
        ".g",
        ".cem",
    }
)

DEFAULT_CREO_MODEL_EXTENSIONS = (
    ".prt",
    ".asm",
    ".drw",
    ".frm",
    ".mfg",
    ".lay",
    ".sec",
    ".dgm",
    ".rep",
    ".mrk",
    ".int",
    ".g",
    ".cem",
    ".tmu",
    ".tmz",
    ".apr",
    ".pvz",
    ".ol",
    ".ed",
    ".edz",
    ".pvs",
    ".stp",
    ".step",
    ".igs",
    ".iges",
    ".dxf",
    ".dwg",
    ".stl",
    ".vda",
    ".neu",
    ".ibl",
    ".pts",
    ".rwd",
    ".rwt",
    ".mrs",
    ".xdb",
    ".cgm",
    ".obj",
    ".wrl",
    ".emn",
    ".idx",
    ".emp",
    ".icm",
    ".bdl",
    ".pkg",
    ".sdp",
    ".sda",
    ".sdac",
    ".sdpc",
    ".mi",
    ".bi",
    ".asc",
    ".sat",
    ".sab",
    ".x_t",
    ".xmt_txt",
    ".x_b",
    ".xmt_bin",
    ".x_n",
    ".xmt_neu",
    ".xmt",
    ".p_b",
    ".model",
    ".exp",
    ".session",
    ".ai",
    ".tsh",
    ".vtx",
    ".acs",
    ".ipt",
    ".iam",
    ".sldprt",
    ".sldasm",
    ".catpart",
    ".catproduct",
    ".cgr",
    ".3dm",
    ".usd",
    ".sla",
    ".par",
    ".psm",
    ".3mf",
    ".she",
)

_PREVIOUS_CREO_MODELS_BASE = frozenset(
    {
        ".prt",
        ".asm",
        ".drw",
        ".frm",
        ".mfg",
        ".lay",
        ".sec",
        ".dgm",
        ".rep",
        ".mrk",
        ".int",
        ".g",
        ".cem",
        ".stp",
        ".step",
        ".igs",
        ".iges",
        ".dxf",
        ".dwg",
        ".stl",
        ".vda",
        ".ipt",
        ".iam",
        ".catpart",
        ".catproduct",
        ".model",
        ".exp",
        ".sldprt",
        ".sldasm",
        ".bdl",
        ".pkg",
        ".sdp",
        ".sda",
        ".sdac",
        ".sdpc",
    }
)

PREVIOUS_DEFAULT_CREO_MODEL_SETS = (
    _PREVIOUS_CREO_MODELS_BASE,
    _PREVIOUS_CREO_MODELS_BASE | {".tmu"},
    _PREVIOUS_CREO_MODELS_BASE | {".tmu", ".pvz"},
)

OBJECT_TYPE_BY_EXTENSION: dict[str, ObjectType] = {
    ".prt": ObjectType.CREO_PART,
    ".asm": ObjectType.CREO_ASSEMBLY,
    ".drw": ObjectType.CREO_DRAWING,
    ".mfg": ObjectType.CREO_MANUFACTURING,
    ".step": ObjectType.STEP,
    ".stp": ObjectType.STEP,
    ".iges": ObjectType.STEP,
    ".igs": ObjectType.STEP,
    ".pdf": ObjectType.PDF,
    ".doc": ObjectType.DOCUMENT,
    ".docx": ObjectType.DOCUMENT,
    ".xls": ObjectType.SPREADSHEET,
    ".xlsx": ObjectType.SPREADSHEET,
    ".csv": ObjectType.SPREADSHEET,
    ".txt": ObjectType.TEXT,
    ".jpg": ObjectType.IMAGE,
    ".jpeg": ObjectType.IMAGE,
    ".png": ObjectType.IMAGE,
}

DEFAULT_FOLDER_BY_TYPE: dict[ObjectType, str] = {
    ObjectType.CREO_PART: "CAD",
    ObjectType.CREO_ASSEMBLY: "CAD",
    ObjectType.CREO_DRAWING: "CAD",
    ObjectType.CREO_MANUFACTURING: "CAD",
    ObjectType.CAD: "CAD",
    ObjectType.STEP: "Exports",
    ObjectType.PDF: "Documents",
    ObjectType.DOCUMENT: "Documents",
    ObjectType.SPREADSHEET: "Documents",
    ObjectType.IMAGE: "Documents",
    ObjectType.TEXT: "Documents",
    ObjectType.OTHER: "Documents",
}

DOCUMENT_OBJECT_TYPES = frozenset(
    {
        ObjectType.PDF,
        ObjectType.DOCUMENT,
        ObjectType.SPREADSHEET,
        ObjectType.IMAGE,
        ObjectType.TEXT,
    }
)

CAD_OBJECT_TYPES = frozenset(
    {
        ObjectType.CREO_PART,
        ObjectType.CREO_ASSEMBLY,
        ObjectType.CREO_DRAWING,
        ObjectType.CREO_MANUFACTURING,
        ObjectType.CAD,
        ObjectType.STEP,
    }
)

OTHER_OBJECT_TYPES = frozenset(item for item in ObjectType if item not in CAD_OBJECT_TYPES)

METRIC_TYPE_FILTERS: dict[str, frozenset[str] | None] = {
    "files": None,
    "creo_parts": frozenset({ObjectType.CREO_PART.value}),
    "assemblies": frozenset({ObjectType.CREO_ASSEMBLY.value}),
    "drawings": frozenset({ObjectType.CREO_DRAWING.value}),
    "documents": frozenset(item.value for item in DOCUMENT_OBJECT_TYPES),
    "other": frozenset(item.value for item in OTHER_OBJECT_TYPES),
}

DEFAULT_LFS_PATTERNS = [
    "*.prt",
    "*.prt.*",
    "*.asm",
    "*.asm.*",
    "*.drw",
    "*.drw.*",
    "*.mfg",
    "*.mfg.*",
    "*.step",
    "*.stp",
    "*.iges",
    "*.igs",
]

DEFAULT_OPENABLE_CAD_EXTENSIONS = (
    ".ncl",
    ".tap",
    ".xml",
    ".log",
)

DEFAULT_EXTRA_CAD_EXTENSIONS = (
    ".tph",
    ".inf",
    ".out",
    ".tool",
    ".crc",
    ".dat",
    ".m_p",
    ".bom",
    ".tbl",
    ".xch",
    ".sym",
    ".bin",
    ".stk",
    ".mrd",
    ".xpr",
    ".mtl",
)

DEFAULT_TYPE_LABELS: tuple[dict[str, str], ...] = (
    {"extension": ".prt", "label": "Part"},
    {"extension": ".asm", "label": "Assembly"},
    {"extension": ".drw", "label": "Drawing"},
    {"extension": ".ncl", "label": "CL Data"},
    {"extension": ".tap, .nc, .cnc, .gcode", "label": "G-Code"},
    {"extension": ".frm", "label": "Drawing Format"},
    {"extension": ".sec", "label": "Section"},
    {"extension": ".lay", "label": "Layout"},
    {"extension": ".mfg", "label": "Manufacturing Model"},
    {"extension": ".stp, .step", "label": "STEP Model"},
    {"extension": ".igs, .iges", "label": "IGES Model"},
    {"extension": ".stl", "label": "STL Model"},
    {"extension": ".x_t, .x_b", "label": "Parasolid Model"},
    {"extension": ".sat", "label": "ACIS Model"},
    {"extension": ".jt", "label": "JT Model"},
    {"extension": ".dxf", "label": "DXF Drawing"},
    {"extension": ".dwg", "label": "DWG Drawing"},
    {"extension": ".pdf", "label": "PDF Document"},
    {"extension": ".pvz, .pvs, .ol", "label": "Creo View package"},
    {"extension": ".log", "label": "Log file"},
    {"extension": "mc_error.log", "label": "ModelCHECK Error Log"},
    {"extension": ".bin", "label": "NC Stock Model"},
    {"extension": ".txt", "label": "Text File"},
    {"extension": ".tmp", "label": "Temp File"},
    {"extension": ".xml", "label": "XML File"},
    {"extension": "mw_settings.xml", "label": "Module Works Settings"},
    {"extension": ".idx, .xas, .xpr", "label": "Instance Accelerator"},
    {"extension": ".tool", "label": "Module Works File"},
    {"extension": ".doc, .docx", "label": "Word Document"},
    {"extension": ".xls, .xlsx", "label": "Excel Document"},
    {"extension": ".csv", "label": "CSV File"},
    {"extension": ".ppt, .pptx", "label": "PowerPoint Presentation"},
    {"extension": ".stk", "label": "Stock Model"},
    {"extension": ".dtl", "label": "Drawing Setup File"},
    {"extension": ".sym", "label": "Symbol"},
    {"extension": ".gph", "label": "UDF/Group File"},
    {"extension": ".ibl", "label": "IBL Curve Data"},
    {"extension": ".pts", "label": "Point Data File"},
    {"extension": ".scl", "label": "System Colors"},
    {"extension": ".mtl", "label": "Material File"},
    {"extension": ".mrd", "label": "Material Removal Data"},
    {"extension": ".tpm", "label": "Tool Parameters"},
    {"extension": ".tph", "label": "Toolpath"},
    {"extension": "reviewref.inf", "label": "Reference Info"},
    {"extension": ".zip, .rar, .7z, .tar, .gz, .tgz, .bz2, .tbz", "label": "Archive"},
    {
        "extension": ".jpg, .jpeg, .tif, .bmp, .png, .gif, .svg, .tiff, .ico, .heic, .eps, .emf, .wmf",
        "label": "Image File",
    },
    {"extension": ".html, .htm", "label": "Webpage"},
    {"extension": ".bat, .cmd, .ps1, .py", "label": "Scripts/programming"},
    {"extension": ".md", "label": "Markdown"},
    {"extension": ".json", "label": "JSON"},
    {"extension": ".mil", "label": "NC Parameters"},
    {"extension": ".txf", "label": "Cutting Tool File"},
    {"extension": ".ppr", "label": "PPrint File"},
    {"extension": ".pro, .sup", "label": "Creo Configuration"},
    {"extension": ".dmt", "label": "Appearance File"},
    {"extension": ".exe", "label": "Executable"},
    {"extension": ".rbn", "label": "Ribbon File"},
    {"extension": ".hol", "label": "Hole File"},
    {"extension": ".mcc, .mcg, .mcs, .mcq, .mcr, .mch, .mcn", "label": "ModelCHECK"},
    {"extension": ".ini", "label": "Configuration File"},
    {
        "extension": ".avi, .mpg, .mpeg, .mp4, .m4v, .mov, .wmv, .mkv, .webm, .flv, .3gp, .3g2, .mts, .m2ts, .ts, .vob, .ogv, .asf, .rm, .rmvb, .divx, .f4v, .mxf",
        "label": "Video",
    },
    {
        "extension": ".mp3, .wav, .wma, .aac, .m4a, .flac, .ogg, .oga, .opus, .aiff, .aif, .amr, .mid, .midi, .ac3, .mka, .ra, .ape, .au, .caf",
        "label": "Audio",
    },
    {"extension": ".tbl", "label": "Creo Table File"},
    {
        "extension": ".ttf, .otf, .ttc, .otc, .woff, .woff2, .eot, .pfb, .pfm, .afm, .fon, .fnt",
        "label": "Font",
    },
    {"extension": ".cfg", "label": "Tree Configuration"},
    {"extension": ".ui", "label": "UI Configuration"},
    {"extension": ".apr", "label": "Ansys Project"},
    {"extension": ".rwd, .rwt, .mrs, .xdb", "label": "Simulate Results"},
    {"extension": ".neu", "label": "Neutral Model"},
    {"extension": ".tmu, .tmz", "label": "Design Exploration Session"},
    {"extension": ".g", "label": "Granite File"},
    {"extension": ".sldprt", "label": "SOLIDWORKS Part"},
    {"extension": ".sldasm", "label": "SOLIDWORKS Assembly"},
    {"extension": ".slddrw", "label": "SOLIDWORKS Drawing"},
    {"extension": ".3mf", "label": "3MF Model"},
    {"extension": ".obj", "label": "OBJ Model"},
    {"extension": ".ipt", "label": "Inventor Part"},
    {"extension": ".iam", "label": "Inventor Assembly"},
    {"extension": ".idw", "label": "Inventor Drawing"},
    {"extension": ".par", "label": "Solid Edge Part"},
    {"extension": ".psm", "label": "Solid Edge Assembly"},
    {"extension": ".dft", "label": "Solid Edge Draft"},
    {"extension": ".rtf", "label": "Rich Text Document"},
    {"extension": ".mpp", "label": "Microsoft Project"},
    {"extension": ".trail", "label": "Trail File"},
)

PREVIOUS_DEFAULT_TYPE_LABEL_SETS = (
    (),
)

DEFAULT_IGNORE_PATTERNS = (
    "*.tst",
    "*.err",
    "*.acl",
    "trail.txt*",
    "std.out",
    "std.err",
    "proimpex.errors",
    "regen_backup_model*.mrd.*",
    "traceback.log",
    "mapkeys.pro",
    "config.pro",
    "config.sup",
    "creo_parametric_customization.ui",
    ".exe",
)

PREVIOUS_DEFAULT_IGNORE_SETS = (
    frozenset(
        {
            "*.tst",
            "*.err",
            "*.acl",
            "trail.txt*",
            "std.out",
            "std.err",
            "proimpex.errors",
        }
    ),
    frozenset(
        {
            "*.tst",
            "*.err",
            "*.acl",
            "trail.txt*",
            "std.out",
            "std.err",
            "proimpex.errors",
            "regen_backup_model*.mrd.*",
        }
    ),
    frozenset(
        {
            "*.tst",
            "*.err",
            "*.acl",
            "trail.txt*",
            "std.out",
            "std.err",
            "proimpex.errors",
            "regen_backup_model*.mrd.*",
            "traceback.log",
            "mapkeys.pro",
            "config.pro",
            "config.sup",
            "creo_parametric_customization.ui",
        }
    ),
)

PREVIOUS_DEFAULT_EXTRA_CAD_SETS = (
    frozenset({".dxf", ".dwg", ".ncl", ".tph", ".nc", ".tap", ".cnc"}),
    frozenset(
        {
            ".ncl",
            ".dxf",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".idx",
            ".log",
            ".step",
            ".stp",
            ".ipt",
            ".stl",
            ".wrl",
            ".sec",
            ".crc",
        }
    ),
    frozenset(
        {
            ".ncl",
            ".dxf",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".idx",
            ".log",
            ".step",
            ".stp",
            ".ipt",
            ".stl",
            ".wrl",
            ".sec",
            ".crc",
            ".dat",
            ".m_p",
            ".bom",
            ".igs",
            ".tbl",
            ".frm",
            ".mfg",
            ".dgm",
            ".lay",
            ".xch",
            ".sym",
        }
    ),
    frozenset(
        {
            ".ncl",
            ".dxf",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".idx",
            ".log",
            ".step",
            ".stp",
            ".ipt",
            ".stl",
            ".wrl",
            ".sec",
            ".crc",
            ".dat",
            ".m_p",
            ".bom",
            ".igs",
            ".tbl",
            ".frm",
            ".mfg",
            ".dgm",
            ".lay",
            ".xch",
            ".sym",
            ".bin",
            ".stk",
            ".mrd",
            ".xpr",
        }
    ),
    frozenset(
        {
            ".ncl",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".idx",
            ".log",
            ".wrl",
            ".crc",
            ".dat",
            ".m_p",
            ".bom",
            ".tbl",
            ".xch",
            ".sym",
            ".bin",
            ".stk",
            ".mrd",
            ".xpr",
        }
    ),
    frozenset(
        {
            ".ncl",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".log",
            ".crc",
            ".dat",
            ".m_p",
            ".bom",
            ".tbl",
            ".xch",
            ".sym",
            ".bin",
            ".stk",
            ".mrd",
            ".xpr",
        }
    ),
    frozenset(
        {
            ".ncl",
            ".tap",
            ".tph",
            ".inf",
            ".xml",
            ".out",
            ".tool",
            ".log",
            ".crc",
            ".dat",
            ".m_p",
            ".bom",
            ".tbl",
            ".xch",
            ".sym",
            ".bin",
            ".stk",
            ".mrd",
            ".xpr",
            ".mtl",
        }
    ),
)
