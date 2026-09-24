from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app


def test_agent_health_and_materialize(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    seen: list[str] = []

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
                "project_id": "proj1",
                "filename": "top.asm",
                "disk_name": "top.asm.1",
                "companions": [
                    {
                        "object_id": "pin",
                        "project_id": "proj1",
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
        assert any("/api/objects/pin/content" in url for url in seen)
        workdir = client.get("/workdir", params={"project_id": "proj1"})
        assert workdir.status_code == 200
        assert workdir.json()["path"].endswith("proj1")


def test_agent_open_folder_uses_project_cache(tmp_path, monkeypatch):
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
        ok = client.post("/open-folder", json={"project_id": "proj1", "folder": "drawings"})
        assert ok.status_code == 200, ok.text
        assert opened[-1].resolve() == nested.resolve()
        root_ok = client.post("/open-folder", json={"project_id": "proj1"})
        assert root_ok.status_code == 200, root_ok.text
        assert opened[-1].resolve() == (root / "proj1").resolve()
        denied = client.post(
            "/open-folder",
            json={"project_id": "proj1", "folder": "..\\..\\Windows"},
        )
        assert denied.status_code == 403


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
        lambda initial_dir, title="Add files to the project": [sample],
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


def test_agent_pick_folder(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    folder = tmp_path / "models"
    folder.mkdir()
    part = folder / "shaft.prt.2"
    part.write_bytes(b"prt")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_folder",
        lambda initial_dir, title="Add a folder to the project": folder,
    )
    with TestClient(app) as client:
        picked = client.post(
            "/pick-folder",
            json={"initial_directory": str(tmp_path), "title": "Add folder"},
        )
        assert picked.status_code == 200, picked.text
        body = picked.json()
        assert body["cancelled"] is False
        assert body["folder"] == str(folder)
        assert str(part) in body["selected"]


def test_agent_pick_folder_cancel(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    monkeypatch.setattr(
        "creopdm.utils.native_dialog.pick_folder",
        lambda initial_dir, title="Add a folder to the project": None,
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
                "project_id": "proj1",
                "absolute_paths": [str(part)],
                "base_folder": str(folder),
            },
        )
        assert response.status_code == 200, response.text
        assert uploaded
        assert uploaded[0][1] == "kit/sub/pin.prt.1"


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
                "project_id": "proj1",
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
                "project_id": "proj1",
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
    project_id = "proj-push"
    cache = root / project_id
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
                "project_id": project_id,
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


def test_agent_push_uploads_latest_extra_cad_numbered_save(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    project_id = "proj-tph"
    cache = root / project_id
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
                "project_id": project_id,
                "items": [{"object_id": "obj-tph", "filename": "op10.tph.1"}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["ok"]) == 1
        assert body["ok"][0]["filename"] == "op10.tph.10"
        assert puts[0]["filename"] == "op10.tph.10"
        assert puts[0]["body"] == b"newest-tph"


def test_agent_lists_and_pushes_new_cache_paths(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    project_id = "proj-new"
    cache = root / project_id
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
                    "object_id": project_id,
                    "filename": files["file"][0],
                    "path": f"/vault/{files['file'][0]}",
                    "bytes_written": len(body),
                },
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        listed = client.get(f"/files?project_id={project_id}")
        assert listed.status_code == 200, listed.text
        names = {item["relative_path"] for item in listed.json()["files"]}
        assert names == {"notes.txt", "nested/extra.txt"}

        response = client.post(
            "/push-paths",
            json={
                "pdm_url": "http://pdm.example:52113",
                "project_id": project_id,
                "relative_paths": ["notes.txt", "nested/extra.txt", "missing.txt"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert {item["filename"] for item in body["ok"]} == {"notes.txt", "extra.txt"}
        assert len(body["failed"]) == 1
        assert body["failed"][0]["filename"] == "missing.txt"
        assert len(puts) == 2
        assert all("/api/projects/" in item["url"] and "workspace-content" in item["url"] for item in puts)
        assert puts[0]["headers"].get("Authorization") == "Bearer tok"

        deleted = client.post(
            "/delete-paths",
            json={
                "project_id": project_id,
                "relative_paths": ["notes.txt", "nested/extra.txt", "gone.txt"],
            },
        )
        assert deleted.status_code == 200, deleted.text
        deleted_body = deleted.json()
        assert {item["filename"] for item in deleted_body["ok"]} == {"notes.txt", "extra.txt"}
        assert len(deleted_body["failed"]) == 1
        assert not (cache / "notes.txt").exists()
        assert not (cache / "nested" / "extra.txt").exists()


def test_agent_delete_paths_trashes_creo_numbered_siblings(tmp_path):
    root = tmp_path / "cache"
    project_id = "proj-del-sib"
    cache = root / project_id
    cache.mkdir(parents=True)
    (cache / "shaft.prt.1").write_bytes(b"v1")
    (cache / "shaft.prt.3").write_bytes(b"v3")
    (cache / "other.prt.1").write_bytes(b"keep")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), token="tok")
    app = create_agent_app(settings)
    with TestClient(app) as client:
        deleted = client.post(
            "/delete-paths",
            json={"project_id": project_id, "relative_paths": ["shaft.prt"]},
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
                "project_id": "proj-add",
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


def test_agent_purge_versions_deletes_only_older_than_vault_floor(tmp_path):
    root = tmp_path / "cache"
    project_id = "proj-purge"
    cache = root / project_id
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
                "project_id": project_id,
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
                "project_id": project_id,
                "floors": [{"logical_path": "shaft.prt", "min_keep": 0}],
            },
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["deleted"] == 0
        assert (cache / "shaft.prt.3").is_file()


def test_agent_purge_versions_dry_run_lists_without_deleting(tmp_path):
    root = tmp_path / "cache"
    project_id = "proj-purge-dry"
    cache = root / project_id
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
                "project_id": project_id,
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
