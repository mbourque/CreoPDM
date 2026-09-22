import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import _extract_flat_zip, create_agent_app


def test_extract_flat_zip_writes_basenames_only(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/part.prt.1", b"nested-part")
        zf.writestr("top.asm.2", b"top-asm")
    extracted, nbytes = _extract_flat_zip(archive, target)
    assert extracted == 2
    assert nbytes == len(b"nested-part") + len(b"top-asm")
    assert (target / "part.prt.1").read_bytes() == b"nested-part"
    assert (target / "top.asm.2").read_bytes() == b"top-asm"


def test_agent_materialize_zip_downloads_and_extracts(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    project_id = "proj-zip"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("shaft.prt.1", b"shaft-bytes")
        zf.writestr("bracket.prt.1", b"bracket-bytes")
    zip_bytes = buf.getvalue()
    seen: list[str] = []

    class FakeStreamResponse:
        status_code = 200

        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            yield self._body

        def read(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, json=None, headers=None):
            seen.append(url)
            assert method == "POST"
            assert json and json.get("object_ids") == ["a", "b"]
            return FakeStreamResponse(zip_bytes)

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/materialize-zip",
            json={
                "pdm_url": "http://pdm.example:52113",
                "project_id": project_id,
                "object_ids": ["a", "b"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["extracted_count"] == 2
        assert body["bytes_written"] == len(b"shaft-bytes") + len(b"bracket-bytes")
        cache = Path(body["working_directory"])
        assert (cache / "shaft.prt.1").read_bytes() == b"shaft-bytes"
        assert (cache / "bracket.prt.1").read_bytes() == b"bracket-bytes"
        assert any("agent-cache-archive" in url for url in seen)
