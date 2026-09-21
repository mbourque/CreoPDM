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
