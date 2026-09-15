from types import SimpleNamespace

from creopdm.utils.folders import (
    folder_crumbs,
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
    }
    nested = folder_view_counts(objects, "Incoming/lib")
    assert nested["files"] == 1
    assert nested["creo_parts"] == 1


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
