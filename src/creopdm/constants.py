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
        ".gph",
        ".dgm",
        ".tbl",
        ".sym",
        ".xch",
    }
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

METRIC_TYPE_FILTERS: dict[str, frozenset[str] | None] = {
    "files": None,
    "creo_parts": frozenset({ObjectType.CREO_PART.value}),
    "assemblies": frozenset({ObjectType.CREO_ASSEMBLY.value}),
    "drawings": frozenset({ObjectType.CREO_DRAWING.value}),
    "documents": frozenset(item.value for item in DOCUMENT_OBJECT_TYPES),
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

DEFAULT_EXTRA_CAD_EXTENSIONS = (
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
)
