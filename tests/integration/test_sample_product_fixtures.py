"""Create folder + Add files / folder / folders / Compressed data… (sample_product fixtures)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_git

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_DIR = FIXTURES / "sample_product"
SAMPLE_ZIP = FIXTURES / "sample_product.zip"

# Logical vault tips after numbered-save collapse (.prt.17 → .prt, etc.).
EXPECTED_RELATIVE_PATHS = {
    "assembly/assembly-model.asm",
    "assembly/sub.asm",
    "assembly/part1.prt",
    "assembly/part2.prt",
    "sheetmetal/sheetmetal-part.prt",
    "sheetmetal/sheetmetal-part.drw",
    "parts/shaft.prt",
    "parts/note.txt",
}


def _create_product(client, repo_parent: Path):
    location = repo_parent / "SampleFixture"
    location.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/products",
        json={"name": "Sample Fixture", "number": "FIX-001"},
    )
    assert response.status_code == 201, response.text
    return response.json(), location


def _listing_paths(client, product_id: str) -> set[str]:
    rows = client.get(f"/api/products/{product_id}/objects").json()
    return {str(item["relative_path"]).replace("\\", "/") for item in rows}


def _assert_fixtures_present() -> None:
    assert SAMPLE_DIR.is_dir(), f"missing {SAMPLE_DIR}"
    assert SAMPLE_ZIP.is_file(), f"missing {SAMPLE_ZIP}"
    assert (SAMPLE_DIR / "parts" / "shaft.prt.17").is_file()
    assert (SAMPLE_DIR / "assembly" / "assembly-model.asm.1").is_file()


@requires_git
def test_sample_product_fixtures_on_disk():
    """Guard: committed fixtures stay usable for Add coverage."""
    _assert_fixtures_present()
    tips = {
        path.relative_to(SAMPLE_DIR).as_posix()
        for path in SAMPLE_DIR.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }
    assert "parts/shaft.prt.17" in tips
    assert "parts/note.txt" in tips
    assert "assembly/part1.prt.1" in tips
    assert "sheetmetal/sheetmetal-part.drw.1" in tips


@requires_git
def test_sample_product_from_zip_imports_nested_tree(client, repo_parent, data_dir):
    """Compressed data… with sample_product.zip → nested vault tips (strip outer folder)."""
    _assert_fixtures_present()
    product, _location = _create_product(client, repo_parent)
    pid = product["uuid"]
    payload = SAMPLE_ZIP.read_bytes()
    added = client.post(
        f"/api/products/{pid}/objects/from-zip",
        files={"file": ("sample_product.zip", payload, "application/zip")},
        data={"parent_folder": "", "comment": "Fixture zip", "strip_single_root": "1"},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["failed"] == [], body["failed"]
    ok_names = {item["filename"] for item in body["ok"]}
    assert ok_names == {
        "assembly-model.asm",
        "sub.asm",
        "part1.prt",
        "part2.prt",
        "sheetmetal-part.prt",
        "sheetmetal-part.drw",
        "shaft.prt",
        "note.txt",
    }
    listing = _listing_paths(client, pid)
    assert listing == EXPECTED_RELATIVE_PATHS

    vault = data_dir / "vaults" / pid
    for rel in EXPECTED_RELATIVE_PATHS:
        assert (vault / rel).is_file(), rel

    # Duplicate zip → already in product (no second tip).
    again = client.post(
        f"/api/products/{pid}/objects/from-zip",
        files={"file": ("sample_product.zip", payload, "application/zip")},
        data={"parent_folder": "", "strip_single_root": "1"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["ok"] == []
    assert len(again.json()["failed"]) == 8


@requires_git
def test_sample_product_create_folder(client, repo_parent, data_dir):
    """Create folder… at product root and nested under a parent; empty folder stays on Files."""
    product, _location = _create_product(client, repo_parent)
    pid = product["uuid"]

    root = client.post(
        f"/api/products/{pid}/folders",
        json={"name": "Incoming", "parent_folder": ""},
    )
    assert root.status_code == 201, root.text
    assert root.json()["path"] == "Incoming"
    assert root.json()["name"] == "Incoming"

    nested = client.post(
        f"/api/products/{pid}/folders",
        json={"name": "Drawings", "parent_folder": "Incoming"},
    )
    assert nested.status_code == 201, nested.text
    assert nested.json()["path"] == "Incoming/Drawings"

    vault = data_dir / "vaults" / pid
    assert (vault / "Incoming" / ".gitkeep").is_file()
    assert (vault / "Incoming" / "Drawings" / ".gitkeep").is_file()

    page = client.get(f"/?product={pid}")
    assert page.status_code == 200, page.text
    assert 'data-folder="Incoming"' in page.text

    under = client.get(f"/?product={pid}&folder=Incoming")
    assert under.status_code == 200, under.text
    assert 'data-folder="Incoming/Drawings"' in under.text

    # Empty created folder accepts Add files… under that location.
    note = SAMPLE_DIR / "parts" / "note.txt"
    added = client.post(
        f"/api/products/{pid}/objects/from-uploads",
        files=[("files", (note.name, note.read_bytes(), "application/octet-stream"))],
        data={
            "relative_paths": ["Incoming/Drawings/note.txt"],
            "comment": "Into created folder",
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["failed"] == []
    assert _listing_paths(client, pid) == {"Incoming/Drawings/note.txt"}
    assert (vault / "Incoming" / "Drawings" / "note.txt").is_file()


@requires_git
def test_sample_product_add_files_multipart(client, repo_parent, data_dir):
    """Add files… uses from-uploads + relative_paths (browser multipart), not single /objects."""
    _assert_fixtures_present()
    product, _location = _create_product(client, repo_parent)
    pid = product["uuid"]

    shaft = SAMPLE_DIR / "parts" / "shaft.prt.17"
    note = SAMPLE_DIR / "parts" / "note.txt"
    part1 = SAMPLE_DIR / "assembly" / "part1.prt.1"

    # Match Add files… / test_objects from-uploads: files[] + relative_paths list.
    resp = client.post(
        f"/api/products/{pid}/objects/from-uploads",
        files=[
            ("files", (shaft.name, shaft.read_bytes(), "application/octet-stream")),
            ("files", (note.name, note.read_bytes(), "application/octet-stream")),
            ("files", (part1.name, part1.read_bytes(), "application/octet-stream")),
        ],
        data={
            "relative_paths": [
                "parts/shaft.prt.17",
                "parts/note.txt",
                "assembly/part1.prt.1",
            ],
            "comment": "Fixture files",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["failed"] == [], body["failed"]
    assert {item["filename"] for item in body["ok"]} == {
        "shaft.prt",
        "note.txt",
        "part1.prt",
    }

    listing = _listing_paths(client, pid)
    assert listing == {
        "parts/shaft.prt",
        "parts/note.txt",
        "assembly/part1.prt",
    }
    vault = data_dir / "vaults" / pid
    assert (vault / "parts" / "shaft.prt").is_file()
    assert (vault / "parts" / "note.txt").read_text(encoding="utf-8").strip() == "This is a note"


@requires_git
def test_sample_product_add_one_folder(client, repo_parent, data_dir):
    """Add folder… recursive from assembly/ keeps folder name under product root."""
    _assert_fixtures_present()
    product, _location = _create_product(client, repo_parent)
    pid = product["uuid"]
    folder = SAMPLE_DIR / "assembly"
    imported = client.post(
        f"/api/products/{pid}/objects/from-disk",
        json={
            "folder": str(folder),
            "base_folder": str(SAMPLE_DIR),
            "comment": "Fixture folder",
            "recursive": True,
            "keep_root_folder": False,
        },
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["failed"] == [], body["failed"]
    assert {item["filename"] for item in body["ok"]} == {
        "assembly-model.asm",
        "sub.asm",
        "part1.prt",
        "part2.prt",
    }
    listing = _listing_paths(client, pid)
    assert listing == {
        "assembly/assembly-model.asm",
        "assembly/sub.asm",
        "assembly/part1.prt",
        "assembly/part2.prt",
    }
    vault = data_dir / "vaults" / pid
    assert (vault / "assembly" / "assembly-model.asm").is_file()


@requires_git
def test_sample_product_add_folders(client, repo_parent, data_dir):
    """Add folders… imports sibling trees (assembly + sheetmetal + parts) in one call."""
    _assert_fixtures_present()
    product, _location = _create_product(client, repo_parent)
    pid = product["uuid"]
    imported = client.post(
        f"/api/products/{pid}/objects/from-disk",
        json={
            "folders": [
                str(SAMPLE_DIR / "assembly"),
                str(SAMPLE_DIR / "sheetmetal"),
                str(SAMPLE_DIR / "parts"),
            ],
            "base_folder": str(SAMPLE_DIR),
            "comment": "Fixture folders",
            "recursive": True,
            "keep_root_folder": False,
        },
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["failed"] == [], body["failed"]
    assert len(body["ok"]) == 8
    listing = _listing_paths(client, pid)
    assert listing == EXPECTED_RELATIVE_PATHS

    page = client.get(f"/?product={pid}")
    assert page.status_code == 200, page.text
    assert 'data-folder="assembly"' in page.text
    assert 'data-folder="sheetmetal"' in page.text
    assert 'data-folder="parts"' in page.text

    vault = data_dir / "vaults" / pid
    for rel in EXPECTED_RELATIVE_PATHS:
        assert (vault / rel).is_file(), rel
