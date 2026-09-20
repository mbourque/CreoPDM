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
