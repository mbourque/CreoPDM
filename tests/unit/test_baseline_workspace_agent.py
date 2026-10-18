"""Tray agent: rebuild a baseline on this PC (exact, hash-verified, read-only, own folder)."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm_agent.baseline_workspace import MARKER_NAME
from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app

PDM = "http://pdm.example:52113"
FOLDER = "Design_Review-abcdef12"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(files: dict[str, bytes], **overrides) -> dict:
    return {
        "baseline": {"uuid": "abcdef12-0000-4000-8000-000000000000", "name": "Design Review"},
        "product": {"uuid": "p1", "name": "Gearbox", "vault_folder": "gearbox"},
        "folder": FOLDER,
        "read_only": True,
        "files": [
            {
                "object_uuid": f"o-{index}",
                "version_uuid": f"v-{index}",
                "filename": name,
                "relative_path": name,
                "display_version": "A.1",
                "sha256": overrides.get("sha", {}).get(name, _sha(data)),
                "size": len(data),
                "content_path": f"/api/baselines/b/versions/v-{index}/content",
            }
            for index, (name, data) in enumerate(files.items())
        ],
    }


class _Response:
    def __init__(self, status: int, content: bytes = b"", message: str = ""):
        self.status_code = status
        self.content = content
        self._message = message

    def json(self):
        return {"error": {"message": self._message}}


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    served: dict[str, _Response] = {}
    seen: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            seen.append(url)
            path = url.replace(PDM, "")
            return served.get(path, _Response(404, b"", "not found"))

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(create_agent_app(settings)) as client:
        yield client, root, served, seen


def _serve(served, files: dict[str, bytes]):
    for index, data in enumerate(files.values()):
        served[f"/api/baselines/b/versions/v-{index}/content"] = _Response(200, data)


def _add(client, manifest, **extra):
    return client.post(
        "/baseline-workspace",
        json={"pdm_url": PDM, "product_id": "p1", "vault_folder": "gearbox", "manifest": manifest, **extra},
    )


def _baseline_root(root: Path) -> Path:
    return root / "_baselines" / "gearbox" / FOLDER


def _is_read_only(path: Path) -> bool:
    return not (stat.S_IMODE(path.stat().st_mode) & stat.S_IWRITE)


FILES = {"shaft.prt": b"shaft-B.2", "housing.prt": b"housing-A.1"}


def test_the_exact_files_are_installed_read_only_in_their_own_folder(agent):
    client, root, served, _seen = agent
    # The product's normal workspace folder has the user's own, newer copy of a file.
    product_dir = root / "gearbox"
    product_dir.mkdir(parents=True)
    (product_dir / "shaft.prt").write_bytes(b"my-working-copy-C.4")

    _serve(served, FILES)
    response = _add(client, _manifest(FILES))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["files_total"] == 2 and body["downloaded"] == 2 and body["kept"] == 0
    assert body["read_only"] is True and body["extras"] == []
    assert Path(body["path"]) == _baseline_root(root).resolve()

    target = _baseline_root(root)
    assert (target / "shaft.prt").read_bytes() == b"shaft-B.2"
    assert (target / "housing.prt").read_bytes() == b"housing-A.1"
    assert _is_read_only(target / "shaft.prt") and _is_read_only(target / "housing.prt")
    marker = json.loads((target / MARKER_NAME).read_text(encoding="utf-8"))
    assert {entry["path"] for entry in marker["files"]} == set(FILES)
    # The working folder is untouched, and no staging folder is left behind.
    assert (product_dir / "shaft.prt").read_bytes() == b"my-working-copy-C.4"
    assert not [p for p in target.parent.iterdir() if ".partial-" in p.name]


def test_a_hash_mismatch_rejects_the_file_and_installs_nothing(agent):
    client, root, served, _seen = agent
    _serve(served, FILES)
    served["/api/baselines/b/versions/v-1/content"] = _Response(200, b"corrupted-bytes")

    response = _add(client, _manifest(FILES))
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "housing.prt" in detail["message"] and "SHA-256" in detail["failures"][0]["reason"]
    assert not _baseline_root(root).exists()  # not even the good file was installed
    assert not [p for p in _baseline_root(root).parent.glob(".*partial*")]


def test_missing_content_fails_explicitly_and_nothing_is_substituted(agent):
    client, root, served, seen = agent
    _serve(served, FILES)
    served["/api/baselines/b/versions/v-0/content"] = _Response(
        409, b"", "shaft.prt B.2 is not in the vault. No other version is substituted."
    )
    response = _add(client, _manifest(FILES))
    assert response.status_code == 502, response.text
    failure = response.json()["detail"]["failures"][0]
    assert failure["file"] == "shaft.prt" and "not in the vault" in failure["reason"]
    assert not _baseline_root(root).exists()
    # Only the exact version URLs were ever requested: no "latest" content endpoint.
    assert all("/api/baselines/b/versions/" in url for url in seen)


def test_existing_correct_files_are_kept_and_different_ones_need_confirmation(agent):
    client, root, served, _seen = agent
    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200

    again = _add(client, _manifest(FILES)).json()  # everything already correct
    assert again["downloaded"] == 0 and again["kept"] == 2

    target = _baseline_root(root)
    edited = target / "shaft.prt"
    edited.chmod(stat.S_IWRITE | stat.S_IREAD)
    edited.write_bytes(b"someone-edited-this")
    refused = _add(client, _manifest(FILES))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["conflicts"] == ["shaft.prt"]
    assert edited.read_bytes() == b"someone-edited-this"  # nothing was changed

    replaced = _add(client, _manifest(FILES), overwrite=True)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["replaced"] == 1 and replaced.json()["downloaded"] == 1
    assert edited.read_bytes() == b"shaft-B.2" and _is_read_only(edited)


def test_check_reports_modified_missing_and_extra_files_and_remove_deletes_only_the_baseline(agent):
    client, root, served, _seen = agent
    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200
    target = _baseline_root(root)
    folder = {"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER}

    clean = client.post("/baseline-workspace/check", json=folder).json()
    assert clean["installed"] is True
    assert clean["missing"] == [] and clean["modified"] == [] and clean["extras"] == []

    # Creo saved a new numbered file into the folder, and a file was edited and another deleted.
    (target / "shaft.prt.2").write_bytes(b"creo-save")
    (target / "housing.prt").chmod(stat.S_IWRITE | stat.S_IREAD)
    (target / "housing.prt").write_bytes(b"edited")
    (target / "shaft.prt").chmod(stat.S_IWRITE | stat.S_IREAD)
    (target / "shaft.prt").unlink()
    dirty = client.post("/baseline-workspace/check", json=folder).json()
    assert dirty["missing"] == ["shaft.prt"] and dirty["modified"] == ["housing.prt"]
    assert dirty["extras"] == ["shaft.prt.2"]

    product_dir = root / "gearbox"
    product_dir.mkdir(exist_ok=True)
    (product_dir / "keep.prt").write_bytes(b"mine")
    removed = client.post("/baseline-workspace/remove", json=folder).json()
    assert removed["removed"] is True and not target.exists()
    # Nothing is left behind: not the baseline folder, not the empty product folder, not _baselines.
    assert not (root / "_baselines").exists()
    assert (product_dir / "keep.prt").read_bytes() == b"mine"
    assert client.post("/baseline-workspace/remove", json=folder).json()["removed"] is False


def test_remove_refuses_a_folder_that_was_not_installed_as_a_baseline(agent):
    client, root, _served, _seen = agent
    stray = _baseline_root(root)
    stray.mkdir(parents=True)
    (stray / "important.prt").write_bytes(b"data")
    refused = client.post(
        "/baseline-workspace/remove",
        json={"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER},
    )
    assert refused.status_code == 409, refused.text
    assert "important" not in refused.text and "no .creopdm-baseline.json" in refused.text
    assert (stray / "important.prt").exists()


def test_an_empty_leftover_folder_is_cleared_by_remove(agent):
    client, root, _served, _seen = agent
    leftover = _baseline_root(root)
    (leftover / "sub").mkdir(parents=True)  # no files, no marker: what an interrupted delete leaves
    removed = client.post(
        "/baseline-workspace/remove",
        json={"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] is True and not leftover.exists()


def test_paths_cannot_escape_the_baseline_folder(agent):
    client, root, served, _seen = agent
    files = {"evil.prt": b"x"}
    manifest = _manifest(files)
    manifest["files"][0]["relative_path"] = "../../outside/evil.prt"
    _serve(served, files)
    response = _add(client, manifest)
    assert response.status_code == 200, response.text
    installed = Path(response.json()["path"])
    inside = [p for p in installed.rglob("evil.prt")]
    assert inside and all(installed in p.resolve().parents for p in inside)
    assert not (root / "outside").exists() and not (root / "_baselines" / "outside").exists()


def test_an_empty_or_malformed_manifest_is_refused(agent):
    client, _root, _served, _seen = agent
    empty = _add(client, {"folder": FOLDER, "files": []})
    assert empty.status_code == 400
    no_hash = _manifest({"a.prt": b"x"})
    no_hash["files"][0]["sha256"] = ""
    assert _add(client, no_hash).status_code == 400


# ---- Creo's Save writes a NEW numbered file, so the folders are locked too (Windows) ----------


USER = "PC" + chr(92) + "engineer"


class _Run:
    def __init__(self, calls, returncode=0):
        self.calls = calls
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        # The tray runs without a console: a missing stdin makes Windows fail with "the handle is
        # invalid", so every icacls/whoami call must pass an explicit stdin.
        assert kwargs.get("stdin") is not None, "subprocess needs an explicit stdin under pythonw"

        class _Result:
            stdout = ""
            stderr = "" if self.returncode == 0 else "Access is denied."

        _Result.returncode = self.returncode
        return _Result()


def _windows(monkeypatch, calls, returncode=0):
    monkeypatch.setattr("creopdm_agent.baseline_workspace._is_windows", lambda: True)
    monkeypatch.setattr("creopdm_agent.baseline_workspace._windows_user", lambda: USER)
    monkeypatch.setattr("creopdm_agent.baseline_workspace.subprocess.run", _Run(calls, returncode))


def test_folders_are_locked_so_creo_cannot_save_a_new_numbered_file(agent, monkeypatch):
    client, root, served, _seen = agent
    calls: list[list[str]] = []
    _windows(monkeypatch, calls)
    files = {"shaft.prt": b"shaft", "sub/pin.prt": b"pin"}
    _serve(served, files)

    response = _add(client, _manifest(files))
    assert response.status_code == 200, response.text
    assert response.json()["folder_locked"] is True
    denies = [c for c in calls if "/deny" in c]
    locked = {Path(c[1]).relative_to(_baseline_root(root).resolve()).as_posix() for c in denies}
    assert locked == {".", "sub"}  # the baseline folder and its subfolder
    assert all(c[-1] == f"{USER}:(WD,AD)" for c in denies)
    # Installing again opens the folders only while files are written, then locks them again.
    calls.clear()
    assert _add(client, _manifest(files)).status_code == 200
    kinds = ["deny" if "/deny" in c else "remove" for c in calls]
    assert kinds[0] == "remove" and kinds[-1] == "deny"


def test_removing_a_baseline_unlocks_its_folders_first(agent, monkeypatch):
    client, root, served, _seen = agent
    calls: list[list[str]] = []
    _windows(monkeypatch, calls)
    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200
    calls.clear()
    folder = {"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER}
    assert client.post("/baseline-workspace/remove", json=folder).json()["removed"] is True
    assert calls and all("/remove:d" in c for c in calls)
    assert not _baseline_root(root).exists()


def test_a_failed_lock_does_not_fail_the_install_but_is_reported(agent, monkeypatch):
    client, root, served, _seen = agent
    calls: list[list[str]] = []
    _windows(monkeypatch, calls, returncode=5)
    _serve(served, FILES)
    response = _add(client, _manifest(FILES))
    assert response.status_code == 200, response.text
    assert response.json()["folder_locked"] is False
    assert "Access is denied" in response.json()["lock_error"]  # the user is told why
    assert (_baseline_root(root) / "shaft.prt").read_bytes() == b"shaft-B.2"


def test_nothing_is_locked_off_windows(agent, monkeypatch):
    client, _root, served, _seen = agent
    calls: list[list[str]] = []
    monkeypatch.setattr("creopdm_agent.baseline_workspace._is_windows", lambda: False)
    monkeypatch.setattr("creopdm_agent.baseline_workspace.subprocess.run", _Run(calls))
    _serve(served, FILES)
    response = _add(client, _manifest(FILES))
    assert response.status_code == 200 and response.json()["folder_locked"] is False
    assert calls == []


def test_removing_one_baseline_keeps_the_others_and_their_parent_folders(agent):
    client, root, served, _seen = agent
    _serve(served, FILES)
    other = _manifest(FILES)
    other["folder"] = "Other_Baseline-11111111"
    assert _add(client, _manifest(FILES)).status_code == 200
    assert _add(client, other).status_code == 200
    removed = client.post(
        "/baseline-workspace/remove",
        json={"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER},
    ).json()
    assert removed["removed"] is True and not _baseline_root(root).exists()
    assert (root / "_baselines" / "gearbox" / "Other_Baseline-11111111" / "shaft.prt").is_file()


def test_a_folder_held_open_by_creo_is_cleared_and_reported_then_finished_later(agent, monkeypatch):
    """Creo as working directory (or Explorer) can hold the folder itself open: the files still go."""
    client, root, served, _seen = agent
    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200
    target = _baseline_root(root)
    folder = {"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER}

    def locked_by_creo(_path):
        raise OSError("WinError 32: the process cannot access the file")

    monkeypatch.setattr("creopdm_agent.baseline_workspace.move_to_trash", locked_by_creo)
    monkeypatch.setattr("creopdm_agent.baseline_workspace._remove_empty_dir", lambda _p: False)
    monkeypatch.setattr("creopdm_agent.baseline_workspace.shutil.rmtree", lambda *a, **k: None)
    first = client.post("/baseline-workspace/remove", json=folder)
    assert first.status_code == 200, first.text
    assert first.json()["removed"] is True and first.json()["folder_in_use"] is True
    assert target.is_dir() and not any(p.is_file() for p in target.rglob("*"))  # files and marker gone

    monkeypatch.undo()
    again = client.post("/baseline-workspace/remove", json=folder).json()  # Creo has let go
    assert again["removed"] is True and again["folder_in_use"] is False
    assert not target.exists() and not (root / "_baselines").exists()


def test_open_folder_shows_a_downloaded_copy_and_refuses_one_that_is_not_there(agent, monkeypatch):
    client, root, served, _seen = agent
    opened: list[Path] = []
    monkeypatch.setattr("creopdm.utils.launch.open_windows_folder", lambda path: opened.append(Path(path)))
    folder = {"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER}

    missing = client.post("/baseline-workspace/open", json=folder)
    assert missing.status_code == 404 and "not been downloaded" in missing.text and opened == []

    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200
    shown = client.post("/baseline-workspace/open", json=folder)
    assert shown.status_code == 200, shown.text
    assert shown.json()["opened"] is True
    assert opened == [_baseline_root(root).resolve()]


def test_the_marker_file_is_hidden_like_the_workspace_cache_index(agent, monkeypatch):
    client, root, served, _seen = agent
    calls: list[tuple[str, bool]] = []
    real = __import__("creopdm.utils.files", fromlist=["set_hidden"]).set_hidden

    def recording(path, hidden=True):
        calls.append((Path(path).name, bool(hidden)))
        real(path, hidden)

    monkeypatch.setattr("creopdm.utils.files.set_hidden", recording)
    _serve(served, FILES)
    assert _add(client, _manifest(FILES)).status_code == 200
    assert calls == [(MARKER_NAME, True)]  # first install: written, then hidden

    calls.clear()
    assert _add(client, _manifest(FILES)).status_code == 200
    # Installing again must unhide before rewriting (Windows refuses to write a Hidden file).
    assert calls == [(MARKER_NAME, False), (MARKER_NAME, True)]
    # And it is still readable by check/remove afterwards.
    folder = {"product_id": "p1", "vault_folder": "gearbox", "folder": FOLDER}
    assert client.post("/baseline-workspace/check", json=folder).json()["installed"] is True
