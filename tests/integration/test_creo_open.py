from pathlib import Path

from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.creo.null_connector import NullCreoConnector
from creopdm.creo.windows_connector import WindowsCreoConnector
from creopdm.services.creo_service import CreoService
from creopdm.utils.identity import StaticUserProvider
from tests.conftest import requires_git


class RecordingConnector(NullCreoConnector):
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def is_available(self) -> bool:
        return True

    def open_model(self, path: Path) -> None:
        self.opened.append(path)


@requires_git
def test_open_in_creo_uses_connector(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        location = repo_parent / "OpenProj"
        project = client.post(
            "/api/projects",
            json={"name": "Open", "repository_path": str(location)},
        ).json()
        created = client.post(
            f"/api/projects/{project['uuid']}/objects",
            files={"file": ("base.prt", b"solid", "application/octet-stream")},
            data={"comment": "Add base"},
        )
        assert created.status_code == 201, created.text
        opened = client.post("/api/creo/open", json={"object_id": created.json()["uuid"]})
        assert opened.status_code == 200, opened.text
        assert opened.json()["method"] == "creo"
        assert opened.json()["filename"] == "base.prt"
        assert opened.json()["working_directory"] == str(recorder.opened[0].parent)
        assert recorder.opened
        assert recorder.opened[0].name == "base.prt"
        assert recorder.opened[0].parent.name == project["uuid"]


@requires_git
def test_open_after_checkin_despite_creo_numbered_workspace_file(
    data_dir, repo_parent, identity: StaticUserProvider
):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        location = repo_parent / "Plywood"
        project = client.post(
            "/api/projects",
            json={"name": "Plywood", "repository_path": str(location)},
        ).json()
        created = client.post(
            f"/api/projects/{project['uuid']}/objects",
            files={"file": ("nested-plywood.prt", b"original", "application/octet-stream")},
            data={"comment": "Add plywood"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        assert client.post(f"/api/objects/{obj_id}/checkout").status_code == 200
        workspace = data_dir / "workspaces" / project["uuid"]
        (workspace / "nested-plywood.prt.1").write_bytes(b"creo-iteration")
        checked = client.post(
            f"/api/objects/{obj_id}/checkin",
            json={"comment": "Saved from Creo"},
        )
        assert checked.status_code == 200, checked.text
        (workspace / "nested-plywood.prt.2").write_bytes(b"creo-after-checkin")
        opened = client.post("/api/creo/open", json={"object_id": obj_id})
        assert opened.status_code == 200, opened.text
        assert recorder.opened
        assert recorder.opened[-1].name == "nested-plywood.prt.1"
        assert recorder.opened[-1].read_bytes() == b"creo-iteration"


def test_windows_connector_respects_executable_override(tmp_path: Path):
    fake = tmp_path / "parametric.exe"
    fake.write_bytes(b"fake")
    connector = WindowsCreoConnector(executable=str(fake))
    assert connector.is_available() is True
    assert connector.find_executable() == fake


def test_windows_connector_association_uses_startfile(tmp_path: Path, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr("creopdm.utils.launch.os.name", "nt")
    monkeypatch.setattr("creopdm.creo.windows_connector.os.name", "nt")

    def fake_start(path: Path, workdir: Path) -> None:
        opened.append(Path(path))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    model = tmp_path / "CAD" / "shaft.prt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"solid")
    connector = WindowsCreoConnector(open_mode="association")
    connector.open_model(model)
    assert opened[0] == model.resolve()


def test_windows_connector_starts_in_model_directory(tmp_path: Path, monkeypatch):
    fake = tmp_path / "parametric.exe"
    fake.write_bytes(b"fake")
    cad = tmp_path / "workspaces" / "6d88bcc5-f3fb-4d83-a782-4ef79c43c24f" / "CAD"
    cad.mkdir(parents=True)
    model = cad / "shaft.prt"
    model.write_bytes(b"solid")
    launched: dict[str, object] = {}

    def fake_popen(args, cwd=None, shell=False, **kwargs):
        launched["args"] = list(args)
        launched["cwd"] = cwd
        launched["shell"] = shell

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr("creopdm.utils.launch.subprocess.Popen", fake_popen)
    connector = WindowsCreoConnector(executable=str(fake), open_mode="executable")
    connector.open_model(model)
    assert launched["cwd"] == str(cad.resolve())
    assert launched["args"] == [str(fake), "shaft.prt"]
    assert launched["shell"] is False


@requires_git
def test_open_document_uses_windows_association(data_dir, repo_parent, identity, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr("creopdm.services.creo_service.os.name", "nt")
    monkeypatch.setattr("creopdm.utils.launch.os.name", "nt")

    def fake_start(path: Path, workdir: Path) -> None:
        opened.append(Path(path))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        location = repo_parent / "DocsProj"
        project = client.post(
            "/api/projects",
            json={"name": "Docs", "repository_path": str(location)},
        ).json()
        created = client.post(
            f"/api/projects/{project['uuid']}/objects",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"comment": "Notes"},
        )
        assert created.status_code == 201, created.text
        opened_resp = client.post("/api/creo/open", json={"object_id": created.json()["uuid"]})
        assert opened_resp.status_code == 200, opened_resp.text
        assert opened_resp.json()["method"] == "shell"
        assert opened
        assert opened[0].name == "notes.txt"
        assert opened[0].parent.name == project["uuid"]
