"""One stuck file must not hold a whole Collect: the per-file Toolkit wait is short for parts/drawings."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app

ROOT = Path(__file__).resolve().parents[2]


def _agent(tmp_path, monkeypatch, seen_timeouts):
    root = tmp_path / "cache"
    root.mkdir()
    app = create_agent_app(
        AgentConfig(host="127.0.0.1", port=8766, local_root=str(root), toolkit_base_url="http://127.0.0.1:8767")
    )

    class FakeResponse:
        status_code = 200

        def __init__(self, body):
            self.content = json.dumps(body).encode("utf-8")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen_timeouts.append(kwargs.get("timeout"))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse(
                {"ok": True, "fileName": "a.prt", "domains": {"identity": {"ok": True, "identity": {"file_name": "a.prt"}}}}
            )

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    return app


def test_the_agent_uses_the_wait_the_page_asks_for_within_limits(tmp_path, monkeypatch):
    seen: list = []
    with TestClient(_agent(tmp_path, monkeypatch, seen)) as client:
        assert client.get("/toolkit/snapshot", params={"filename": "a.prt", "timeout": "40"}).status_code == 200
        client.get("/toolkit/snapshot", params={"filename": "a.prt", "timeout": "5"})  # too short: raised
        client.get("/toolkit/snapshot", params={"filename": "a.prt", "timeout": "9999"})  # too long: capped
        client.get("/toolkit/snapshot", params={"filename": "a.prt"})  # nothing asked: as before
    assert seen == [40.0, 10.0, 180.0, 120.0]


def test_the_page_asks_for_a_short_wait_except_for_assemblies():
    script = (ROOT / "src" / "creopdm" / "static" / "js" / "creo_workspace.js").read_text(encoding="utf-8")
    assert "/\.(asm|mfg)$/i.test(tip) ? 120 : 40" in script
    assert 'query.set("timeout", String(seconds));' in script
    assert "abortSignalAfter((seconds + 10) * 1000)" in script
