from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app


def test_agent_health_and_materialize(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    seen: list[str] = []
    # Fixed vault mtime so materialize must not leave "now" on disk.
    vault_mtime = 1_700_000_000.0
    from email.utils import formatdate

    class FakeResponse:
        def __init__(self, body: bytes):
            self.status_code = 200
            self.content = body
            self.headers = {"Last-Modified": formatdate(vault_mtime, usegmt=True)}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            seen.append(url)
            if "/api/objects/abc/content" in url:
                return FakeResponse(b"asm-bytes")
            if "/api/objects/pin/content" in url:
                return FakeResponse(b"prt-bytes")
            return FakeResponse(b"other")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert health.json()["app"] == "creopdm-agent"
        assert "status_poll_interval_seconds" in health.json()
        saved = client.post(
            "/materialize",
            json={
                "pdm_url": "http://pdm.example:52113",
                "object_id": "abc",
                "product_id": "proj1",
                "filename": "top.asm",
                "disk_name": "top.asm.1",
                "companions": [
                    {
                        "object_id": "pin",
                        "product_id": "proj1",
                        "filename": "pin.prt",
                        "disk_name": "pin.prt.1",
                    }
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["disk_name"] == "top.asm.1"
        assert body["filename"] == "top.asm"
        assert body["companions_written"] == 1
        assert Path(body["path"]).read_bytes() == b"asm-bytes"
        assert (Path(body["working_directory"]) / "pin.prt.1").read_bytes() == b"prt-bytes"
        assert abs(Path(body["path"]).stat().st_mtime - vault_mtime) < 2
        assert abs((Path(body["working_directory"]) / "pin.prt.1").stat().st_mtime - vault_mtime) < 2
        assert any("/api/objects/pin/content" in url for url in seen)
        workdir = client.get("/workdir", params={"product_id": "proj1"})
        assert workdir.status_code == 200
        assert workdir.json()["path"].endswith("proj1")


def test_agent_materialize_preserves_vault_folders(tmp_path, monkeypatch):
    """Nested vault relative_path must create matching folders in the agent cache."""
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    class FakeResponse:
        def __init__(self, body: bytes):
            self.status_code = 200
            self.content = body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse(b"nested-pin")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        saved = client.post(
            "/materialize",
            json={
                "pdm_url": "http://pdm.example:52113",
                "object_id": "pin",
                "product_id": "proj-nested",
                "relative_path": "lib/step/pin.prt",
                "filename": "pin.prt",
                "disk_name": "pin.prt.1",
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        path = Path(body["path"])
        workdir = Path(body["working_directory"])
        assert path == workdir / "lib" / "step" / "pin.prt.1"
        assert path.read_bytes() == b"nested-pin"
        assert not (workdir / "pin.prt.1").exists()


def test_agent_materialize_preserves_spaces_in_vault_folders(tmp_path, monkeypatch):
    """Vault folder 'from ptc' must stay spaced in cache (not from_ptc)."""
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    class FakeResponse:
        def __init__(self, body: bytes):
            self.status_code = 200
            self.content = body
            self.headers = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse(b"gab-bytes")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    product_id = "nc-library"
    cache = root / product_id
    legacy = cache / "NC" / "Fixtures" / "angle-irons" / "from_ptc"
    legacy.mkdir(parents=True)
    (legacy / "gab.prt.1").write_bytes(b"old-sanitized")
    with TestClient(app) as client:
        saved = client.post(
            "/materialize",
            json={
                "pdm_url": "http://pdm.example:52113",
                "object_id": "gab",
                "product_id": product_id,
                "relative_path": "NC/Fixtures/angle-irons/from ptc/gab.prt",
                "filename": "gab.prt",
                "disk_name": "gab.prt.1",
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        path = Path(body["path"])
        workdir = Path(body["working_directory"])
        assert path == workdir / "NC" / "Fixtures" / "angle-irons" / "from ptc" / "gab.prt.1"
        assert path.read_bytes() == b"gab-bytes"
        assert not (legacy / "gab.prt.1").is_file()


def test_agent_materialize_replace_newer_trashes_higher_local_saves(tmp_path, monkeypatch):
    """History revert / open-without-checkout must drop local .prt.3 when vault tip is .prt.1."""
    root = tmp_path / "cache"
    product_id = "proj-replace"
    cache = root / product_id
    nested = cache / "model-templates"
    nested.mkdir(parents=True)
    (nested / "start_part.prt.1").write_bytes(b"stale-1")
    (nested / "start_part.prt.2").write_bytes(b"local-2")
    (nested / "start_part.prt.3").write_bytes(b"local-3")
    (cache / "start_part.prt.3").write_bytes(b"flat-3")
    (nested / "other.prt.9").write_bytes(b"keep")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    class FakeResponse:
        def __init__(self, body: bytes):
            self.status_code = 200
            self.content = body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse(b"vault-1")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        saved = client.post(
            "/materialize",
            json={
                "pdm_url": "http://pdm.example:52113",
                "object_id": "part1",
                "product_id": product_id,
                "relative_path": "model-templates/start_part.prt.1",
                "filename": "start_part.prt.1",
                "disk_name": "start_part.prt.1",
                "replace_newer": True,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["disk_name"] == "start_part.prt.1"
        assert Path(body["path"]).read_bytes() == b"vault-1"
        purged = set(body.get("purged_newer") or [])
        assert "model-templates/start_part.prt.2" in purged
        assert "model-templates/start_part.prt.3" in purged
        assert "start_part.prt.3" in purged
        assert not (nested / "start_part.prt.2").exists()
        assert not (nested / "start_part.prt.3").exists()
        assert not (cache / "start_part.prt.3").exists()
        assert (nested / "start_part.prt.1").is_file()
        assert (nested / "other.prt.9").read_bytes() == b"keep"


def test_agent_materialize_replace_newer_drops_prt2_when_tip_is_logical(tmp_path, monkeypatch):
    """After clean check-in, rematerialize logical tip must trash leftover .prt.2."""
    root = tmp_path / "cache"
    product_id = "5e9399ce-1754-488b-aaa4-290ad5b5d5a2"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "600610010003.prt").write_bytes(b"old-logical")
    (cache / "600610010003.prt.2").write_bytes(b"checked-in-tip")
    (cache / "other.prt.2").write_bytes(b"keep-other")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    class FakeResponse:
        def __init__(self, body: bytes):
            self.status_code = 200
            self.content = body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse(b"vault-logical")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        saved = client.post(
            "/materialize",
            json={
                "pdm_url": "http://pdm.example:52113",
                "object_id": "part-logical",
                "product_id": product_id,
                "relative_path": "600610010003.prt",
                "filename": "600610010003.prt",
                "disk_name": "600610010003.prt",
                "replace_newer": True,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["disk_name"] == "600610010003.prt"
        assert Path(body["path"]).read_bytes() == b"vault-logical"
        purged = set(body.get("purged_newer") or [])
        assert "600610010003.prt.2" in purged
        assert not (cache / "600610010003.prt.2").exists()
        assert (cache / "600610010003.prt").is_file()
        assert (cache / "other.prt.2").read_bytes() == b"keep-other"


def test_agent_open_folder_uses_product_cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    opened: list[Path] = []

    def fake_open(path):
        opened.append(Path(path))

    monkeypatch.setattr("creopdm.utils.launch.open_windows_folder", fake_open)
    with TestClient(app) as client:
        nested = root / "proj1" / "drawings"
        nested.mkdir(parents=True)
        ok = client.post("/open-folder", json={"product_id": "proj1", "folder": "drawings"})
        assert ok.status_code == 200, ok.text
        assert opened[-1].resolve() == nested.resolve()
        root_ok = client.post("/open-folder", json={"product_id": "proj1"})
        assert root_ok.status_code == 200, root_ok.text
        assert opened[-1].resolve() == (root / "proj1").resolve()
        denied = client.post(
            "/open-folder",
            json={"product_id": "proj1", "folder": "..\\..\\Windows"},
        )
        assert denied.status_code == 403


def test_agent_open_folder_creates_cache_when_nothing_materialized(tmp_path, monkeypatch):
    """Open workspace on an empty product must create the local cache folder."""
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    opened: list[Path] = []

    def fake_open(path):
        # Mirror production: create then "open".
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        opened.append(target)

    monkeypatch.setattr("creopdm.utils.launch.open_windows_folder", fake_open)
    with TestClient(app) as client:
        assert not (root / "brand-new").exists()
        ok = client.post(
            "/open-folder",
            json={"product_id": "brand-new", "vault_folder": "brand-new"},
        )
        assert ok.status_code == 200, ok.text
        assert (root / "brand-new").is_dir()
        assert opened[-1].resolve() == (root / "brand-new").resolve()


def test_agent_pick_files_and_local_file(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    sample = tmp_path / "outside" / "shaft.prt.3"
    sample.parent.mkdir()
    sample.write_bytes(b"creo")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_files",
        lambda initial_dir, title="Add files to the product", **kwargs: [sample],
    )
    with TestClient(app) as client:
        picked = client.post(
            "/pick-files",
            json={"initial_directory": str(tmp_path), "title": "Add files"},
        )
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["cancelled"] is False
        assert body["selected"] == [str(sample)]
        downloaded = client.get("/local-file", params={"path": str(sample)})
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == b"creo"
        missing = client.get("/local-file", params={"path": str(tmp_path / "nope.prt.1")})
        assert missing.status_code == 404


def test_agent_pick_files_archive_mode_skips_creo_latest_filter(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    zip_path = tmp_path / "pack.zip"
    zip_path.write_bytes(b"PK")
    seen: dict = {}

    def fake_pick(initial_dir, title="Add files to the product", **kwargs):
        seen["filter_mode"] = kwargs.get("filter_mode", "add")
        seen["title"] = title
        return [zip_path]

    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    monkeypatch.setattr("creopdm.utils.native_dialog.pick_files", fake_pick)
    with TestClient(app) as client:
        picked = client.post(
            "/pick-files",
            json={
                "initial_directory": str(tmp_path),
                "title": "Choose a compressed zip file",
                "filter_mode": "archive",
            },
        )
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["selected"] == [str(zip_path)]
        assert seen["filter_mode"] == "archive"


def test_agent_pick_folder(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "models"
    folder.mkdir()
    part = folder / "shaft.prt.2"
    part.write_bytes(b"prt")
    older = folder / "shaft.prt.1"
    older.write_bytes(b"old")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_folder",
        lambda initial_dir, title="Add a folder to the product": folder,
    )
    with TestClient(app) as client:
        picked = client.post(
            "/pick-folder",
            json={
                "initial_directory": str(tmp_path),
                "title": "Add folder",
                "purgeable_extensions": [".prt"],
            },
        )
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["cancelled"] is False
        assert body["folder"] == str(folder)
        assert str(part) in body["selected"]
        assert str(older) not in body["selected"]


def test_agent_pick_folder_non_recursive(tmp_path, monkeypatch):
    """Add Folder mode must not list files under nested subfolders."""
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "models"
    nested = folder / "lib"
    nested.mkdir(parents=True)
    top = folder / "top.prt.1"
    top.write_bytes(b"top")
    deep = nested / "pin.prt.1"
    deep.write_bytes(b"pin")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_folder",
        lambda initial_dir, title="Add a folder to the product": folder,
    )
    with TestClient(app) as client:
        picked = client.post(
            "/pick-folder",
            json={
                "initial_directory": str(tmp_path),
                "purgeable_extensions": [".prt"],
                "recursive": False,
            },
        )
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert str(top) in body["selected"]
        assert str(deep) not in body["selected"]


def test_agent_pick_folder_cancel(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_folder",
        lambda initial_dir, title="Add a folder to the product": None,
    )
    with TestClient(app) as client:
        picked = client.post("/pick-folder", json={})
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["cancelled"] is True
        assert body["selected"] == []
        assert body.get("folder", "") == ""


def test_agent_add_paths_uses_base_folder_for_relative_paths(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "kit"
    nested = folder / "sub"
    nested.mkdir(parents=True)
    part = nested / "pin.prt.1"
    part.write_bytes(b"prt")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [{"filename": "pin.prt", "uuid": "u1"}], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            rels = []
            for item in files or []:
                if item[0] == "relative_paths":
                    rels.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            uploaded.append((url, rels[0] if rels else ""))
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(part)],
                "base_folder": str(folder),
            },
        )
        assert response.status_code == 200, response.text
        assert uploaded
        assert uploaded[0][1] == "kit/sub/pin.prt.1"


def test_agent_add_paths_can_omit_root_folder_name(tmp_path, monkeypatch):
    """keep_root_folder=false stores paths relative to the chosen folder only."""
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "kit"
    nested = folder / "sub"
    nested.mkdir(parents=True)
    part = nested / "pin.prt.1"
    part.write_bytes(b"prt")
    top = folder / "shaft.prt.1"
    top.write_bytes(b"prt")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "relative_paths":
                    uploaded.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(part), str(top)],
                "base_folder": str(folder),
                "keep_root_folder": False,
            },
        )
        assert response.status_code == 200, response.text
        assert set(uploaded) == {"sub/pin.prt.1", "shaft.prt.1"}


def test_agent_add_paths_omits_older_purgeable_versions(tmp_path, monkeypatch):
    """Regression: Settings → Purgeable drives which .ext.N siblings are skipped on upload."""
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "models"
    folder.mkdir()
    older = folder / "shaft.prt.1"
    latest = folder / "shaft.prt.4"
    notes = folder / "notes.pdf"
    older.write_bytes(b"1")
    latest.write_bytes(b"4")
    notes.write_bytes(b"%PDF")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "files":
                    uploaded.append(Path(item[1][0]).name if isinstance(item[1], tuple) else str(item[1]))
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        # Only list the older save — disk sibling scan must still pick .prt.4.
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(older), str(notes)],
                "base_folder": str(folder),
                "purgeable_extensions": [".prt", ".asm"],
            },
        )
        assert response.status_code == 200, response.text
        assert "shaft.prt.4" in uploaded
        assert "shaft.prt.1" not in uploaded
        assert "notes.pdf" in uploaded


def test_agent_add_paths_preserves_sibling_subfolders_under_chosen_folder(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    docs = tmp_path / "Documents"
    lib = docs / "Camtasia"
    pdf = docs / "PDF"
    lib.mkdir(parents=True)
    pdf.mkdir(parents=True)
    video = lib / "demo.mp4"
    sheet = pdf / "notes.pdf"
    video.write_bytes(b"mp4")
    sheet.write_bytes(b"pdf")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "relative_paths":
                    uploaded.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(video), str(sheet)],
                "base_folder": str(docs),
            },
        )
        assert response.status_code == 200, response.text
        assert set(uploaded) == {
            "Documents/Camtasia/demo.mp4",
            "Documents/PDF/notes.pdf",
        }


def test_agent_add_paths_skips_outside_base_instead_of_flattening(tmp_path, monkeypatch):
    """Regression: resolve()/relative_to failure used to land basename-only under Documents/."""
    root = tmp_path / "cache"
    root.mkdir()
    docs = tmp_path / "Documents"
    snagit = docs / "Snagit"
    snagit.mkdir(parents=True)
    inside = snagit / "capture.png"
    inside.write_bytes(b"png")
    outside = tmp_path / "elsewhere" / "capture.png"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"png")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "relative_paths":
                    uploaded.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(inside), str(outside)],
                "base_folder": str(docs),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert uploaded == ["Documents/Snagit/capture.png"]
        assert "Documents/capture.png" not in uploaded
        failed = body.get("failed") or []
        assert any(item.get("code") == "OUTSIDE_BASE" for item in failed)
        assert any(item.get("filename") == "capture.png" for item in failed)


def test_agent_add_paths_skips_empty_files_before_upload(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    empty = docs / "blank.docx"
    empty.write_bytes(b"")
    real = docs / "notes.docx"
    real.write_bytes(b"docx")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [{"filename": "notes.docx", "uuid": "u1"}], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "relative_paths":
                    uploaded.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(empty), str(real)],
                "base_folder": str(docs),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert uploaded == ["Documents/notes.docx"]
        failed = body.get("failed") or []
        assert any(item.get("code") == "EMPTY" and item.get("filename") == "blank.docx" for item in failed)


def test_agent_add_paths_keeps_documents_root_files(tmp_path, monkeypatch):
    """Files directly under the chosen folder (not only subfolders) must keep Documents/name."""
    root = tmp_path / "cache"
    root.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    top = docs / "readme.txt"
    top.write_bytes(b"hi")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[str] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            for item in files or []:
                if item[0] == "relative_paths":
                    uploaded.append(item[1][1] if isinstance(item[1], tuple) else item[1])
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj1",
                "absolute_paths": [str(top)],
                "base_folder": str(docs),
            },
        )
        assert response.status_code == 200, response.text
        assert uploaded == ["Documents/readme.txt"]


def test_agent_open_local_association(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    target = root / "bolt_sw.SLDPRT"
    target.write_bytes(b"sw")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    opened: list[str] = []

    def fake_open(path, cwd=None):
        opened.append(str(path))

    monkeypatch.setattr("creopdm.utils.launch.open_windows_file", fake_open)
    with TestClient(app) as client:
        ok = client.post("/open", json={"path": str(target)})
        assert ok.status_code == 200, ok.text
        assert ok.json()["mode"] == "association"
        assert opened and Path(opened[0]).name == "bolt_sw.SLDPRT"
        denied = client.post("/open", json={"path": str(tmp_path / "outside.bin")})
        assert denied.status_code == 403


def test_agent_open_local_creo(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    target = root / "bolt_sw.SLDPRT"
    target.write_bytes(b"sw")
    parametric = tmp_path / "parametric.exe"
    parametric.write_bytes(b"")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    started: list[tuple[str, str, bool]] = []

    class FakeConnector:
        def find_executable(self):
            return parametric

    def fake_start(executable, path, cwd=None, *, logical_name=True):
        started.append((str(executable), str(path), logical_name))

    monkeypatch.setattr(
        "creopdm.creo.windows_connector.WindowsCreoConnector",
        FakeConnector,
    )
    monkeypatch.setattr("creopdm.utils.launch.start_executable", fake_start)
    with TestClient(app) as client:
        ok = client.post("/open", json={"path": str(target), "mode": "creo"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["mode"] == "creo"
        assert started == [(str(parametric), str(target.resolve()), False)]


def test_agent_health_reports_status_poll_zero(tmp_path):
    root = tmp_path / "cache"
    settings = AgentConfig(
        host="127.0.0.1",
        port=8766,
        local_root=str(root),
        health_interval_seconds=0,
        status_poll_interval_seconds=0,
    )
    app = create_agent_app(settings)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["ok"] is True
        assert body["health_interval_seconds"] == 0
        assert body["status_poll_interval_seconds"] == 0


def test_agent_push_uploads_latest_cache_file(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    product_id = "proj-push"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "shaft.prt.3").write_bytes(b"older")
    (cache / "shaft.prt.4").write_bytes(b"agent-local-save")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    puts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, files=None):
            handle = files["file"][1]
            body = handle.read()
            puts.append(
                {
                    "url": url,
                    "headers": headers or {},
                    "filename": files["file"][0],
                    "body": body,
                }
            )
            return FakeResponse(
                200,
                {
                    "ok": True,
                    "object_id": "obj-1",
                    "filename": files["file"][0],
                    "path": "/vault/shaft.prt.4",
                    "bytes_written": len(body),
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/push",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": product_id,
                "items": [
                    {"object_id": "obj-1", "filename": "shaft.prt"},
                    {"object_id": "missing", "filename": "ghost.prt"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["ok"]) == 1
        assert body["ok"][0]["object_id"] == "obj-1"
        assert body["ok"][0]["filename"] == "shaft.prt.4"
        assert body["ok"][0]["bytes_written"] == len(b"agent-local-save")
        assert len(body["failed"]) == 1
        assert body["failed"][0]["object_id"] == "missing"
        assert len(puts) == 1
        assert puts[0]["url"].endswith("/api/objects/obj-1/workspace-content")
        assert puts[0]["filename"] == "shaft.prt.4"
        assert puts[0]["body"] == b"agent-local-save"
        assert puts[0]["headers"].get("Authorization") == "Bearer tok"


def test_agent_push_finds_newer_save_in_cache_subfolder(tmp_path, monkeypatch):
    """Push must find the highest .ext.N by logical name across nested cache folders."""
    root = tmp_path / "cache"
    product_id = "proj-nested-push"
    cache = root / product_id
    nested = cache / "Documents"
    nested.mkdir(parents=True)
    (nested / "shaft.prt.1").write_bytes(b"old")
    (nested / "shaft.prt.2").write_bytes(b"nested-save")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    puts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, files=None):
            handle = files["file"][1]
            body = handle.read()
            puts.append({"filename": files["file"][0], "body": body})
            return FakeResponse(
                200,
                {
                    "ok": True,
                    "object_id": "obj-1",
                    "filename": files["file"][0],
                    "path": "/vault/Documents/shaft.prt.2",
                    "bytes_written": len(body),
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/push",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": product_id,
                "items": [{"object_id": "obj-1", "filename": "Documents/shaft.prt.1"}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["ok"]) == 1
        assert body["ok"][0]["filename"] == "shaft.prt.2"
        assert puts[0]["body"] == b"nested-save"


def test_agent_push_uploads_latest_extra_cad_numbered_save(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    product_id = "proj-tph"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "op10.tph.1").write_bytes(b"old")
    (cache / "op10.tph.10").write_bytes(b"newest-tph")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    puts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, files=None):
            handle = files["file"][1]
            body = handle.read()
            puts.append({"filename": files["file"][0], "body": body})
            return FakeResponse(
                200,
                {
                    "ok": True,
                    "object_id": "obj-tph",
                    "filename": files["file"][0],
                    "path": "/vault/op10.tph.10",
                    "bytes_written": len(body),
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/push",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": product_id,
                "items": [{"object_id": "obj-tph", "filename": "op10.tph.1"}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["ok"]) == 1
        assert body["ok"][0]["filename"] == "op10.tph.10"
        assert puts[0]["filename"] == "op10.tph.10"
        assert puts[0]["body"] == b"newest-tph"


def test_agent_hash_paths_detects_same_size_different_content(tmp_path):
    """Same byte length, different bytes → different SHA-256 (check-in content replace)."""
    import hashlib

    root = tmp_path / "cache"
    product_id = "proj-hash"
    cache = root / product_id
    cache.mkdir(parents=True)
    a = b"AAAA"
    b = b"BBBB"
    assert len(a) == len(b)
    (cache / "same.prt").write_bytes(a)
    (cache / "nested").mkdir()
    (cache / "nested" / "same.prt").write_bytes(b)
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/hash-paths",
            json={
                "product_id": product_id,
                "relative_paths": ["same.prt", "nested/same.prt", "missing.prt"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        by_path = {item["relative_path"]: item for item in body["files"]}
        assert by_path["same.prt"]["ok"] is True
        assert by_path["nested/same.prt"]["ok"] is True
        assert by_path["missing.prt"]["ok"] is False
        assert by_path["same.prt"]["content_hash"] == hashlib.sha256(a).hexdigest()
        assert by_path["nested/same.prt"]["content_hash"] == hashlib.sha256(b).hexdigest()
        assert by_path["same.prt"]["content_hash"] != by_path["nested/same.prt"]["content_hash"]
        assert by_path["same.prt"]["size"] == 4
        assert by_path["nested/same.prt"]["size"] == 4


def test_agent_lists_and_pushes_new_cache_paths(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    product_id = "proj-new"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "notes.txt").write_bytes(b"hello-local")
    (cache / "nested").mkdir()
    (cache / "nested" / "extra.txt").write_bytes(b"nested-local")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    puts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, files=None):
            handle = files["file"][1]
            body = handle.read()
            puts.append(
                {
                    "url": url,
                    "headers": headers or {},
                    "filename": files["file"][0],
                    "body": body,
                }
            )
            return FakeResponse(
                200,
                {
                    "ok": True,
                    "object_id": product_id,
                    "filename": files["file"][0],
                    "path": f"/vault/{files['file'][0]}",
                    "bytes_written": len(body),
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        listed = client.get(f"/files?product_id={product_id}")
        assert listed.status_code == 200, listed.text
        names = {item["relative_path"] for item in listed.json()["files"]}
        assert names == {"notes.txt", "nested/extra.txt"}

        response = client.post(
            "/push-paths",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": product_id,
                "relative_paths": ["notes.txt", "nested/extra.txt", "missing.txt"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert {item["filename"] for item in body["ok"]} == {"notes.txt", "extra.txt"}
        assert len(body["failed"]) == 1
        assert body["failed"][0]["filename"] == "missing.txt"
        assert len(puts) == 2
        assert all("/api/products/" in item["url"] and "workspace-content" in item["url"] for item in puts)
        assert puts[0]["headers"].get("Authorization") == "Bearer tok"

        deleted = client.post(
            "/delete-paths",
            json={
                "product_id": product_id,
                "relative_paths": ["notes.txt", "nested/extra.txt", "gone.txt"],
            },
        )
        assert deleted.status_code == 200, deleted.text
        deleted_body = deleted.json()
        assert {item["filename"] for item in deleted_body["ok"]} == {"notes.txt", "extra.txt"}
        assert len(deleted_body["failed"]) == 1
        assert not (cache / "notes.txt").exists()
        assert not (cache / "nested" / "extra.txt").exists()


def test_agent_delete_product_cache_removes_folder(tmp_path):
    root = tmp_path / "cache"
    vault = "robot-arm"
    cache = root / vault
    cache.mkdir(parents=True)
    (cache / "shaft.prt.1").write_bytes(b"prt")
    nested = cache / "docs"
    nested.mkdir()
    (nested / "notes.txt").write_text("hi", encoding="utf-8")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/delete-product-cache",
            json={"product_id": "ignored-uuid", "vault_folder": vault},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["deleted"] is True
        assert not cache.exists()
        again = client.post(
            "/delete-product-cache",
            json={"product_id": "ignored-uuid", "vault_folder": vault},
        )
        assert again.status_code == 200, again.text
        assert again.json()["deleted"] is False


def test_agent_delete_paths_trashes_creo_numbered_siblings(tmp_path):
    root = tmp_path / "cache"
    product_id = "proj-del-sib"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "shaft.prt.1").write_bytes(b"v1")
    (cache / "shaft.prt.3").write_bytes(b"v3")
    (cache / "other.prt.1").write_bytes(b"keep")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    with TestClient(app) as client:
        deleted = client.post(
            "/delete-paths",
            json={"product_id": product_id, "relative_paths": ["shaft.prt"]},
        )
        assert deleted.status_code == 200, deleted.text
        names = {item["filename"] for item in deleted.json()["ok"]}
        assert names == {"shaft.prt.1", "shaft.prt.3"}
        assert not (cache / "shaft.prt.1").exists()
        assert not (cache / "shaft.prt.3").exists()
        assert (cache / "other.prt.1").is_file()


def test_agent_add_paths_posts_multipart_to_pdm(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    folder = tmp_path / "models"
    folder.mkdir()
    pin = folder / "pin.prt.1"
    shaft = folder / "shaft.prt.2"
    pin.write_bytes(b"pin-bytes")
    shaft.write_bytes(b"shaft-bytes")
    posts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int = 200, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            file_names = []
            rels = []
            for entry in files or []:
                key, value = entry[0], entry[1]
                if key == "files":
                    file_names.append(value[0])
                    if hasattr(value[1], "read"):
                        value[1].read()
                elif key == "relative_paths":
                    rels.append(value[1] if isinstance(value, tuple) else value)
            posts.append(
                {
                    "url": url,
                    "headers": headers or {},
                    "data": data or {},
                    "file_names": file_names,
                    "relative_paths": rels,
                }
            )
            return FakeResponse(
                200,
                {
                    "ok": [
                        {"uuid": "u1", "filename": "pin.prt.1", "status": "added"},
                        {"uuid": "u2", "filename": "shaft.prt.2", "status": "added"},
                    ],
                    "failed": [],
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": "proj-add",
                "absolute_paths": [str(pin), str(shaft)],
                "comment": "Initial models",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["uuid"] for item in body["ok"]} == {"u1", "u2"}
    assert len(posts) == 1
    assert "from-uploads" in posts[0]["url"]
    assert posts[0]["headers"].get("Authorization") == "Bearer tok"
    assert posts[0]["data"].get("comment") == "Initial models"
    assert set(posts[0]["file_names"]) == {"pin.prt.1", "shaft.prt.2"}


def test_agent_add_paths_comment_on_every_upload_chunk(tmp_path, monkeypatch):
    """Bulk add must not invent 'Add 5 files' on later 5-file upload chunks."""
    root = tmp_path / "src"
    root.mkdir()
    paths = []
    for i in range(12):
        path = root / f"part{i:02d}.prt"
        path.write_bytes(b"x")
        paths.append(str(path))
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(tmp_path / "cache"))
    app = create_agent_app(settings)
    posts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            posts.append({"url": url, "data": dict(data or {}), "files": len(files or [])})
            ok = []
            for entry in files or []:
                if entry[0] == "files":
                    ok.append({"uuid": "u", "filename": entry[1][0], "status": "added"})
            return FakeResponse(200, {"ok": ok, "failed": []})

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        blank = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": "proj-bulk",
                "absolute_paths": paths,
                "client_total": 935,
            },
        )
        assert blank.status_code == 200, blank.text
        assert len(posts) >= 3  # 12 files / chunk_size 5
        assert all(post["data"].get("comment") == "Add 935 files" for post in posts)

        posts.clear()
        typed = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.example:52113",
                "product_id": "proj-bulk",
                "absolute_paths": paths,
                "comment": "Library import",
                "client_total": 935,
            },
        )
        assert typed.status_code == 200, typed.text
        assert all(post["data"].get("comment") == "Library import" for post in posts)


def test_agent_purge_versions_deletes_only_older_than_vault_floor(tmp_path):
    root = tmp_path / "cache"
    product_id = "proj-purge"
    cache = root / product_id
    nested = cache / "sub"
    nested.mkdir(parents=True)
    (cache / "shaft.prt").write_bytes(b"0")
    (cache / "shaft.prt.1").write_bytes(b"1")
    (cache / "shaft.prt.3").write_bytes(b"3")
    (cache / "shaft.prt.4").write_bytes(b"4")
    (cache / "orphan.prt.1").write_bytes(b"orphan")
    (nested / "pin.prt.1").write_bytes(b"1")
    (nested / "pin.prt.2").write_bytes(b"2")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/purge-versions",
            json={
                "product_id": product_id,
                "model_extensions": [".prt", ".asm", ".drw"],
                "floors": [
                    {"logical_path": "shaft.prt", "min_keep": 3},
                    {"logical_path": "sub/pin.prt", "min_keep": 2},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] == 3
        assert {item["filename"] for item in body["ok"]} == {
            "shaft.prt",
            "shaft.prt.1",
            "pin.prt.1",
        }
        assert (cache / "shaft.prt.3").is_file()
        assert (cache / "shaft.prt.4").is_file()
        assert (cache / "orphan.prt.1").is_file()
        assert (nested / "pin.prt.2").is_file()
        assert not (cache / "shaft.prt").exists()
        assert not (cache / "shaft.prt.1").exists()
        assert not (nested / "pin.prt.1").exists()

        empty = client.post(
            "/purge-versions",
            json={
                "product_id": product_id,
                "floors": [{"logical_path": "shaft.prt", "min_keep": 0}],
            },
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["deleted"] == 0
        assert (cache / "shaft.prt.3").is_file()


def test_agent_purge_versions_flat_cache_for_nested_vault_floor(tmp_path):
    """Regression: nested vault floor must purge older saves at the flat cache root."""
    root = tmp_path / "cache"
    product_id = "proj-purge-flat"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "shaft.prt.1").write_bytes(b"1")
    (cache / "shaft.prt.2").write_bytes(b"2")
    (cache / "shaft.prt.3").write_bytes(b"3")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/purge-versions",
            json={
                "product_id": product_id,
                "model_extensions": [".prt", ".asm", ".drw"],
                "floors": [{"logical_path": "Documents/shaft.prt", "min_keep": 3}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] == 2
        assert {item["filename"] for item in body["ok"]} == {"shaft.prt.1", "shaft.prt.2"}
        assert (cache / "shaft.prt.3").is_file()
        assert not (cache / "shaft.prt.1").exists()
        assert not (cache / "shaft.prt.2").exists()


def test_agent_purge_versions_dry_run_lists_without_deleting(tmp_path):
    root = tmp_path / "cache"
    product_id = "proj-purge-dry"
    cache = root / product_id
    cache.mkdir(parents=True)
    (cache / "shaft.prt").write_bytes(b"0")
    (cache / "shaft.prt.1").write_bytes(b"1")
    (cache / "shaft.prt.3").write_bytes(b"3")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/purge-versions",
            json={
                "product_id": product_id,
                "model_extensions": [".prt", ".asm", ".drw"],
                "dry_run": True,
                "floors": [{"logical_path": "shaft.prt", "min_keep": 3}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] == 2
        assert {item["filename"] for item in body["ok"]} == {"shaft.prt", "shaft.prt.1"}
        assert (cache / "shaft.prt").is_file()
        assert (cache / "shaft.prt.1").is_file()
        assert (cache / "shaft.prt.3").is_file()


def test_agent_import_zip_streams_to_from_zip(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    zip_path = tmp_path / "pack.zip"
    zip_path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    uploaded: list[dict] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "ok": [{"filename": "shaft.prt.1", "uuid": "u1", "status": "added"}],
                "failed": [],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            uploaded.append({"url": url, "data": dict(data or {}), "files": files})
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/import-zip",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj-zip",
                "zip_path": str(zip_path),
                "parent_folder": "Drawings",
                "comment": "zip add",
                "token": "tok",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"][0]["filename"] == "shaft.prt.1"
        assert body["failed"] == []
        assert uploaded
        assert uploaded[0]["url"].endswith("/api/products/proj-zip/objects/from-zip")
        assert uploaded[0]["data"]["parent_folder"] == "Drawings"
        assert uploaded[0]["data"]["comment"] == "zip add"


def test_agent_import_zip_rejects_oversize(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    zip_path = tmp_path / "huge.zip"
    zip_path.write_bytes(b"x" * 100)
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), pdm_url="http://pdm.test")
    app = create_agent_app(settings)
    import creopdm.utils.zip_import as zip_mod

    monkeypatch.setattr(zip_mod, "MAX_ZIP_IMPORT_BYTES", 50)
    with TestClient(app) as client:
        response = client.post(
            "/import-zip",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "proj-zip",
                "zip_path": str(zip_path),
            },
        )
        assert response.status_code == 400, response.text
        assert "2 GB" in response.json()["detail"]
