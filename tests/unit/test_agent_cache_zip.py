import hashlib
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import (
    CachePlanItem,
    _extract_cache_zip,
    _plan_cache_downloads,
    create_agent_app,
)


def test_extract_cache_zip_preserves_nested_folders(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("lib/step/part.prt.1", b"nested-part")
        zf.writestr("top.asm.2", b"top-asm")
    extracted, nbytes = _extract_cache_zip(archive, target)
    assert extracted == 2
    assert nbytes == len(b"nested-part") + len(b"top-asm")
    assert (target / "lib" / "step" / "part.prt.1").read_bytes() == b"nested-part"
    assert (target / "top.asm.2").read_bytes() == b"top-asm"
    assert not (target / "part.prt.1").exists()


def test_cache_dest_relative_keeps_vault_folders():
    from creopdm_agent.server import _cache_dest_relative

    assert _cache_dest_relative("lib/step/pin.prt", "pin.prt.1").as_posix() == "lib/step/pin.prt.1"
    assert _cache_dest_relative("pin.prt", "pin.prt.1").as_posix() == "pin.prt.1"
    assert _cache_dest_relative("", "top.asm.1").as_posix() == "top.asm.1"


def test_plan_skips_matching_hash_keeps_newer_save(tmp_path):
    cache = tmp_path / "proj"
    cache.mkdir()
    matching = b"same-bytes"
    digest = hashlib.sha256(matching).hexdigest()
    (cache / "pin.prt.1").write_bytes(matching)
    (cache / "bolt.prt.3").write_bytes(b"local-newer-edit")

    download_ids, skipped, kept = _plan_cache_downloads(
        cache,
        [
            CachePlanItem(
                object_id="match",
                filename="pin.prt.1",
                disk_name="pin.prt.1",
                content_hash=digest,
                file_size=len(matching),
            ),
            CachePlanItem(
                object_id="newer",
                filename="bolt.prt.1",
                disk_name="bolt.prt.1",
                content_hash="abc123",
                file_size=3,
            ),
            CachePlanItem(
                object_id="missing",
                filename="ghost.prt.1",
                disk_name="ghost.prt.1",
                content_hash="deadbeef",
                file_size=4,
            ),
        ],
    )
    assert download_ids == ["missing"]
    assert skipped == 1
    assert kept == 1


def test_agent_materialize_zip_skips_when_cache_matches(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    project_id = "proj-zip"
    cache = root / project_id
    cache.mkdir(parents=True)
    body = b"already-local"
    digest = hashlib.sha256(body).hexdigest()
    (cache / "shaft.prt.1").write_bytes(body)
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    seen: list[str] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            seen.append(url)
            assert "agent-cache-manifest" in url
            return FakeResponse(
                {
                    "project_id": project_id,
                    "items": [
                        {
                            "object_id": "a",
                            "filename": "shaft.prt.1",
                            "disk_name": "shaft.prt.1",
                            "content_hash": digest,
                            "file_size": len(body),
                        }
                    ],
                }
            )

        def stream(self, *args, **kwargs):
            raise AssertionError("archive should not be fetched when cache matches")

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/materialize-zip",
            json={
                "pdm_url": "http://pdm.example:52113",
                "project_id": project_id,
                "object_ids": ["a"],
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["extracted_count"] == 0
        assert payload["skipped_count"] == 1
        assert payload["download_count"] == 0
        assert any("agent-cache-manifest" in url for url in seen)


def test_agent_materialize_zip_downloads_and_extracts(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    project_id = "proj-zip"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("lib/step/shaft.prt.1", b"shaft-bytes")
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

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            seen.append(url)
            return FakeResponse(
                {
                    "project_id": project_id,
                    "items": [
                        {
                            "object_id": "a",
                            "filename": "shaft.prt.1",
                            "disk_name": "shaft.prt.1",
                            "relative_path": "lib/step/shaft.prt",
                            "content_hash": hashlib.sha256(b"shaft-bytes").hexdigest(),
                            "file_size": len(b"shaft-bytes"),
                        },
                        {
                            "object_id": "b",
                            "filename": "bracket.prt.1",
                            "disk_name": "bracket.prt.1",
                            "relative_path": "bracket.prt",
                            "content_hash": hashlib.sha256(b"bracket-bytes").hexdigest(),
                            "file_size": len(b"bracket-bytes"),
                        },
                    ],
                }
            )

        def stream(self, method, url, json=None, headers=None):
            seen.append(url)
            assert method == "POST"
            assert json and set(json.get("object_ids")) == {"a", "b"}
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
        assert body["download_count"] == 2
        cache = Path(body["working_directory"])
        assert (cache / "lib" / "step" / "shaft.prt.1").read_bytes() == b"shaft-bytes"
        assert (cache / "bracket.prt.1").read_bytes() == b"bracket-bytes"
        assert not (cache / "shaft.prt.1").exists()
        assert any("agent-cache-manifest" in url for url in seen)
        assert any("agent-cache-archive" in url for url in seen)
        assert (cache / "_creopdm_cache_index.json").is_file()
