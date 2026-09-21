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
