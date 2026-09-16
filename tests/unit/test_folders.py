from datetime import datetime
from types import SimpleNamespace

from creopdm.utils.folders import (
    folder_crumbs,
    folder_index,
    folder_list_entries,
    folder_of,
    folder_view_counts,
    normalize_folder_query,
)


def test_folder_view_counts_uses_immediate_files_only():
    objects = [
        SimpleNamespace(filename="shaft.prt", relative_path="shaft.prt", object_type="CREO_PART"),
        SimpleNamespace(filename="arm.asm", relative_path="Incoming/arm.asm", object_type="CREO_ASSEMBLY"),
        SimpleNamespace(filename="pin.prt", relative_path="Incoming/lib/pin.prt", object_type="CREO_PART"),
        SimpleNamespace(filename="notes.pdf", relative_path="Incoming/notes.pdf", object_type="PDF"),
    ]
    root = folder_view_counts(objects, "")
    assert root["files"] == 1
    assert root["creo_parts"] == 1
    assert root["assemblies"] == 0
    incoming = folder_view_counts(objects, "Incoming")
    assert incoming == {
        "files": 2,
        "creo_parts": 0,
        "assemblies": 1,
        "drawings": 0,
        "documents": 1,
        "other": 1,
        "checked_out": 0,
    }
    nested = folder_view_counts(objects, "Incoming/lib")
    assert nested["files"] == 1
    assert nested["creo_parts"] == 1
    only_nested = [
        SimpleNamespace(filename="pin.prt", relative_path="ribbed2/pin.prt", object_type="CREO_PART"),
        SimpleNamespace(filename="notes.pdf", relative_path="ribbed2/notes.pdf", object_type="PDF"),
    ]
    assert folder_view_counts(only_nested, "")["files"] == 0


def test_folder_view_counts_checked_out():
    objects = [
        SimpleNamespace(
            filename="shaft.prt",
            relative_path="shaft.prt",
            object_type="CREO_PART",
            owned_by_me=True,
        ),
        SimpleNamespace(
            filename="notes.pdf",
            relative_path="notes.pdf",
            object_type="PDF",
            checkout_user="Bob",
        ),
        SimpleNamespace(filename="pin.prt", relative_path="pin.prt", object_type="CREO_PART"),
    ]
    counts = folder_view_counts(objects, "")
    assert counts["checked_out"] == 2
    assert counts["files"] == 3


def test_folder_of_root_and_nested():
    assert folder_of("shaft.prt") == ""
    assert folder_of("Incoming/shaft.prt") == "Incoming"
    assert folder_of("Incoming/lib/pin.prt") == "Incoming/lib"


def test_normalize_folder_query_rejects_traversal():
    assert normalize_folder_query("Incoming/lib") == "Incoming/lib"
    assert normalize_folder_query("../secret") == ""
    assert normalize_folder_query(None) == ""


def test_folder_crumbs():
    crumbs = folder_crumbs("Incoming/lib")
    assert crumbs == [
        {"name": "Incoming", "path": "Incoming"},
        {"name": "lib", "path": "Incoming/lib"},
    ]


def test_folder_list_entries_shows_only_current_view():
    objects = [
        SimpleNamespace(filename="shaft.prt", relative_path="shaft.prt"),
        SimpleNamespace(filename="pin.prt", relative_path="Incoming/lib/pin.prt"),
        SimpleNamespace(filename="bushing.prt.2", relative_path="Incoming/bushing.prt.2"),
    ]
    root = folder_list_entries(objects)
    kinds = [(item["kind"], item.get("name") or item["object"].filename) for item in root]
    assert kinds == [("folder", "Incoming"), ("file", "shaft.prt")]
    incoming = next(item for item in root if item.get("path") == "Incoming")
    assert incoming["count"] == 2

    inside = folder_list_entries(objects, "Incoming")
    names = [(item["kind"], item.get("name") or item["object"].filename) for item in inside]
    assert names == [("folder", "lib"), ("file", "bushing.prt.2")]

    nested = folder_list_entries(objects, "Incoming/lib")
    assert [item["object"].filename for item in nested if item["kind"] == "file"] == ["pin.prt"]


def test_folder_index_counts_without_loading_files():
    rows = [
        ("shaft.prt", None),
        ("Incoming/arm.asm", None),
        ("Incoming/lib/pin.prt", None),
        ("Incoming/notes.pdf", None),
    ]
    folders, files = folder_index(rows, "")
    assert files == ["shaft.prt"]
    incoming = next(item for item in folders if item["path"] == "Incoming")
    assert incoming["count"] == 3
    nested, nested_files = folder_index(rows, "Incoming")
    assert nested_files == ["Incoming/arm.asm", "Incoming/notes.pdf"]
    assert nested[0]["name"] == "lib"
    assert nested[0]["count"] == 1


def test_folder_index_folder_only_catalog_has_no_file_rows():
    rows = [(f"html_tutorials/page{index}.html", None) for index in range(6)]
    folders, files = folder_index(rows, "")
    assert files == []
    assert len(folders) == 1
    assert folders[0]["name"] == "html_tutorials"
    assert folders[0]["count"] == 6
    nested, nested_files = folder_index(rows, "html_tutorials")
    assert nested == []
    assert len(nested_files) == 6


def test_folder_index_missing_folder_is_empty():
    folders, files = folder_index([("Incoming/pin.prt", None)], "Missing")
    assert folders == []
    assert files == []


def test_folder_index_uses_latest_modified_on_folder():
    older = datetime(2020, 1, 1)
    newer = datetime(2024, 6, 1)
    folders, _ = folder_index(
        [
            ("Incoming/a.prt", older),
            ("Incoming/lib/b.prt", newer),
        ],
        "",
    )
    assert folders[0]["modified"] == newer


def test_folder_index_normalizes_backslashes():
    folders, files = folder_index([("Incoming\\lib\\pin.prt", None)], "")
    assert files == []
    assert folders[0]["path"] == "Incoming"
    assert folders[0]["count"] == 1

