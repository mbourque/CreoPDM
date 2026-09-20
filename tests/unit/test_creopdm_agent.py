from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app


def test_agent_health_and_materialize(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)

    class FakeResponse:
        status_code = 200
        content = b"prt-bytes"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            assert "/api/objects/abc/content" in url
            return FakeResponse()

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
                "filename": "support.prt",
                "disk_name": "support.prt.1",
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["disk_name"] == "support.prt.1"
        assert body["filename"] == "support.prt"
        assert Path(body["path"]).read_bytes() == b"prt-bytes"
        assert body["bytes_written"] == 9
