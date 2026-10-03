from pathlib import Path

from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.creo.null_connector import NullCreoConnector
from creopdm.creo.windows_connector import WindowsCreoConnector
from creopdm.exceptions import CreoUnavailableError
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
        product = client.post(
            "/api/products",
            json={"name": "Open"},
        ).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
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
        assert recorder.opened[0].parent.name == product["uuid"]


@requires_git
def test_open_untracked_workspace_file_by_relative_path(
    data_dir, repo_parent, identity: StaticUserProvider
):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "Queue Open"}).json()
        workspace = data_dir / "vaults" / product["uuid"]
        nested = workspace / "Incoming"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "pin.prt").write_bytes(b"new-pin")
        opened = client.post(
            "/api/creo/open",
            json={"product_id": product["uuid"], "relative_path": "Incoming/pin.prt"},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["method"] == "creo"
        assert opened.json()["filename"] == "pin.prt"
        assert recorder.opened
        assert recorder.opened[-1].name == "pin.prt"
        assert recorder.opened[-1].read_bytes() == b"new-pin"
        missing = client.post(
            "/api/creo/open",
            json={"product_id": product["uuid"], "relative_path": "missing.prt"},
        )
        assert missing.status_code == 400
        rejected = client.post("/api/creo/open", json={"launch": False})
        assert rejected.status_code == 422


@requires_git
def test_open_prepare_does_not_launch(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "Prepare"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("hub.prt", b"solid", "application/octet-stream")},
            data={"comment": "Add hub"},
        )
        assert created.status_code == 201, created.text
        prepared = client.post(
            "/api/creo/open",
            json={"object_id": created.json()["uuid"], "launch": False},
        )
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        assert body["method"] == "prepared"
        assert body["creo_object"] is True
        assert body["filename"] == "hub.prt"
        assert body.get("creo_release") in {None, ""}
        assert Path(body["path"]).name == "hub.prt"
        assert recorder.opened == []


@requires_git
def test_open_prepare_includes_creo_release(data_dir, repo_parent, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "Release Open"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={
                "file": (
                    "shaft.prt.1",
                    (
                        "#UGC:2 PART 1 1 1 1 1 1 1 1 1 1 \\\n"
                        "#-END_OF_UGC_HEADER\n"
                        "#Creo  TM  13  (c) 2026 by PTC Inc.  All Rights Reserved. 13.4.1.0\n"
                        "#UGC_TOC 2 32 81 17#############################################################"
                    ).encode("ascii")
                    + b"\x00bin",
                    "application/octet-stream",
                )
            },
            data={"comment": "Creo 13 part"},
        )
        assert created.status_code == 201, created.text
        prepared = client.post(
            "/api/creo/open",
            json={"object_id": created.json()["uuid"], "launch": False},
        )
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        assert body["creo_release"] == "13.4.1.0"
        assert body["filename"] == "shaft.prt"
        assert body["disk_name"] == "shaft.prt"


@requires_git
def test_open_prepare_skips_creo_release_for_foreign_openable(
    data_dir, repo_parent, identity: StaticUserProvider
):
    """SolidWorks is Creo-openable in File > Open, but Creo.JS cannot open Multi-CAD."""
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "SW Open"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={
                "file": ("bolt_sw.SLDPRT", b"solidworks-part", "application/octet-stream")
            },
            data={"comment": "SW part"},
        )
        assert created.status_code == 201, created.text
        prepared = client.post(
            "/api/creo/open",
            json={"object_id": created.json()["uuid"], "launch": False},
        )
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        assert body["creo_object"] is False
        assert body.get("open_with_creo") is True
        assert body.get("requires_agent_cache") is True
        assert body.get("creo_release") in {None, ""}
        assert body["filename"].lower().endswith(".sldprt")


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
        product = client.post(
            "/api/products",
            json={"name": "Plywood"},
        ).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("nested-plywood.prt", b"original", "application/octet-stream")},
            data={"comment": "Add plywood"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        assert client.post(f"/api/objects/{obj_id}/checkout").status_code == 200
        workspace = data_dir / "vaults" / product["uuid"]
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
        assert recorder.opened[-1].name == "nested-plywood.prt.2"
        assert recorder.opened[-1].read_bytes() == b"creo-after-checkin"


def test_windows_connector_respects_executable_override(tmp_path: Path):
    fake = tmp_path / "parametric.exe"
    fake.write_bytes(b"fake")
    connector = WindowsCreoConnector(executable=str(fake))
    assert connector.is_available() is True
    assert connector.find_executable() == fake


def test_windows_connector_association_uses_startfile(tmp_path: Path, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr("creopdm.creo.windows_connector._is_windows", lambda: True)

    def fake_start(path: Path, workdir: Path) -> None:
        opened.append(Path(path))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    model = tmp_path / "CAD" / "shaft.prt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"solid")
    connector = WindowsCreoConnector(open_mode="association")
    connector.open_model(model)
    assert opened[0] == model.resolve()


def test_windows_connector_embedded_does_not_launch(tmp_path: Path, monkeypatch):
    fake = tmp_path / "parametric.exe"
    fake.write_bytes(b"fake")
    model = tmp_path / "CAD" / "shaft.prt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"solid")
    launched: list[object] = []

    def fake_popen(*args, **kwargs):
        launched.append(args)
        raise AssertionError("embedded mode must not start Creo")

    monkeypatch.setattr("creopdm.utils.launch.subprocess.Popen", fake_popen)
    connector = WindowsCreoConnector(executable=str(fake), open_mode="embedded")
    try:
        connector.open_model(model)
        raise AssertionError("embedded open_model should refuse to launch")
    except CreoUnavailableError as exc:
        assert "built-in browser" in exc.message.lower()
    assert launched == []


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


def test_windows_connector_starts_creo_view(tmp_path: Path, monkeypatch):
    fake = tmp_path / "pview.exe"
    fake.write_bytes(b"fake")
    cad = tmp_path / "workspaces" / "view-proj" / "CAD"
    cad.mkdir(parents=True)
    model = cad / "preview.pvz"
    model.write_bytes(b"viewable")
    launched: dict[str, object] = {}

    def fake_popen(args, cwd=None, shell=False, **kwargs):
        launched["args"] = list(args)
        launched["cwd"] = cwd
        launched["shell"] = shell

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr("creopdm.utils.launch.subprocess.Popen", fake_popen)
    connector = WindowsCreoConnector(view_executable=str(fake), view_open_mode="executable")
    connector.open_view(model)
    assert launched["cwd"] == str(cad.resolve())
    assert launched["args"] == [str(fake), "preview.pvz"]


def test_windows_connector_open_model_view_uses_pview(tmp_path: Path, monkeypatch):
    fake = tmp_path / "pview.exe"
    fake.write_bytes(b"fake")
    cad = tmp_path / "CAD"
    cad.mkdir()
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
    connector = WindowsCreoConnector(
        view_executable=str(fake),
        open_mode="view",
        view_open_mode="executable",
    )
    connector.open_model(model)
    assert launched["cwd"] == str(cad.resolve())
    assert launched["args"] == [str(fake), "shaft.prt"]


def test_windows_connector_view_keeps_numbered_save_ext(tmp_path: Path, monkeypatch):
    fake = tmp_path / "pview.exe"
    fake.write_bytes(b"fake")
    cad = tmp_path / "CAD"
    cad.mkdir()
    model = cad / "if-on-a-cylinder.prt.1"
    model.write_bytes(b"solid")
    launched: dict[str, object] = {}

    def fake_popen(args, cwd=None, shell=False, **kwargs):
        launched["args"] = list(args)
        launched["cwd"] = cwd

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr("creopdm.utils.launch.subprocess.Popen", fake_popen)
    connector = WindowsCreoConnector(
        view_executable=str(fake),
        open_mode="view",
        view_open_mode="executable",
    )
    connector.open_model(model)
    assert launched["cwd"] == str(cad.resolve())
    assert launched["args"] == [str(fake), "if-on-a-cylinder.prt.1"]


def test_windows_connector_finds_view_beside_parametric(tmp_path: Path):
    parametric = tmp_path / "Creo 13.0.0.0" / "Parametric" / "bin" / "parametric.bat"
    pview = tmp_path / "Creo 13.0.0.0" / "View" / "bin" / "pview.exe"
    parametric.parent.mkdir(parents=True)
    pview.parent.mkdir(parents=True)
    parametric.write_text("@echo off\n", encoding="utf-8")
    pview.write_bytes(b"fake")
    connector = WindowsCreoConnector(executable=str(parametric))
    assert connector.find_view_executable() == pview


def test_windows_connector_view_association_uses_startfile(tmp_path: Path, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr("creopdm.creo.windows_connector._is_windows", lambda: True)

    def fake_start(path: Path, workdir: Path) -> None:
        opened.append(Path(path))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    model = tmp_path / "CAD" / "preview.pvz"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"viewable")
    connector = WindowsCreoConnector(view_open_mode="association")
    connector.open_view(model)
    assert opened[0] == model.resolve()


def test_windows_connector_opens_numbered_save_as_logical_name(tmp_path: Path, monkeypatch):
    fake = tmp_path / "parametric.exe"
    fake.write_bytes(b"fake")
    folder = tmp_path / "ribbed2"
    folder.mkdir()
    model = folder / "4259827_cp25.prt.2"
    model.write_bytes(b"creo-save")
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
    assert launched["cwd"] == str(folder.resolve())
    assert launched["args"] == [str(fake), "4259827_cp25.prt"]


@requires_git
def test_open_document_uses_windows_association(data_dir, repo_parent, identity, monkeypatch):
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        product = client.post(
            "/api/products",
            json={"name": "Docs"},
        ).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"comment": "Notes"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        opened_resp = client.post("/api/creo/open", json={"object_id": obj_id})
        assert opened_resp.status_code == 200, opened_resp.text
        body = opened_resp.json()
        assert body["method"] == "browser"
        assert body["url"] == f"/api/objects/{obj_id}/content"
        content = client.get(body["url"])
        assert content.status_code == 200, content.text
        assert content.headers.get("content-disposition", "").startswith("attachment")
        assert content.content == b"hello"


@requires_git
def test_open_extra_cad_uses_windows_association(
    data_dir, repo_parent, identity, monkeypatch
):
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        assert client.put("/api/settings", json={"creo_open_mode": "association"}).status_code == 200
        product = client.post("/api/products", json={"name": "ExtraCad"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("setup.inf", b"info", "application/octet-stream")},
            data={"comment": "Extra CAD"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        opened_resp = client.post("/api/creo/open", json={"object_id": obj_id})
        assert opened_resp.status_code == 200, opened_resp.text
        body = opened_resp.json()
        assert body["method"] == "browser"
        assert body["url"] == f"/api/objects/{obj_id}/content"


@requires_git
def test_open_image_uses_windows_association(data_dir, repo_parent, identity, monkeypatch):
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        assert client.put("/api/settings", json={"creo_open_mode": "embedded"}).status_code == 200
        product = client.post("/api/products", json={"name": "Images"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            data={"comment": "Photo"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        opened_resp = client.post("/api/creo/open", json={"object_id": obj_id})
        assert opened_resp.status_code == 200, opened_resp.text
        body = opened_resp.json()
        assert body["method"] == "browser"
        assert body["url"] == f"/api/objects/{obj_id}/content"
        content = client.get(body["url"])
        assert content.status_code == 200
        assert content.headers.get("content-disposition", "").startswith("attachment")
        assert content.content.startswith(b"\x89PNG")


@requires_git
def test_open_openable_cad_uses_windows_association(
    data_dir, repo_parent, identity, monkeypatch
):
    ctx = build_context(ConfigManager(), users=identity)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "OpenableCad"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("rough.ncl", b"g1 x0", "text/plain")},
            data={"comment": "Openable CAD"},
        )
        assert created.status_code == 201, created.text
        obj_id = created.json()["uuid"]
        opened_resp = client.post("/api/creo/open", json={"object_id": obj_id})
        assert opened_resp.status_code == 200, opened_resp.text
        body = opened_resp.json()
        assert body["method"] == "browser"
        assert body["url"] == f"/api/objects/{obj_id}/content"


class EmbeddedConnector(RecordingConnector):
    def cad_open_mode(self) -> str:
        return "embedded"


@requires_git
def test_open_embedded_does_not_launch_cad(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = EmbeddedConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "Embedded"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("cover.prt", b"solid", "application/octet-stream")},
            data={"comment": "Add cover"},
        )
        assert created.status_code == 201, created.text
        object_id = created.json()["uuid"]
        opened = client.post("/api/creo/open", json={"object_id": object_id})
        assert opened.status_code == 400, opened.text
        assert "built-in browser" in opened.json()["error"]["message"].lower()
        assert recorder.opened == []
        prepared = client.post(
            "/api/creo/open",
            json={"object_id": object_id, "launch": False},
        )
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["method"] == "prepared"
        assert prepared.json()["creo_object"] is True
        assert recorder.opened == []


@requires_git
def test_open_viewable_uses_creo_view(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "Viewable"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("preview.pvz", b"viewable", "application/octet-stream")},
            data={"comment": "Add viewable"},
        )
        assert created.status_code == 201, created.text
        opened = client.post("/api/creo/open", json={"object_id": created.json()["uuid"]})
        assert opened.status_code == 200, opened.text
        assert opened.json()["method"] == "creo_view"
        assert opened.json()["creo_object"] is False
        assert opened.json()["filename"] == "preview.pvz"
        assert recorder.opened
        assert recorder.opened[0].name == "preview.pvz"


class ViewModeConnector(RecordingConnector):
    def cad_open_mode(self) -> str:
        return "view"


@requires_git
def test_open_creo_model_with_view_mode(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = ViewModeConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "ViewModels"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("shaft.prt", b"solid", "application/octet-stream")},
            data={"comment": "Add shaft"},
        )
        assert created.status_code == 201, created.text
        opened = client.post("/api/creo/open", json={"object_id": created.json()["uuid"]})
        assert opened.status_code == 200, opened.text
        assert opened.json()["method"] == "creo_view"
        assert opened.json()["creo_object"] is False
        assert recorder.opened
        assert recorder.opened[0].name == "shaft.prt"


@requires_git
def test_open_embedded_still_opens_creo_view(data_dir, repo_parent, identity: StaticUserProvider):
    recorder = EmbeddedConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "EmbeddedView"}).json()
        created = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("preview.pvz", b"viewable", "application/octet-stream")},
            data={"comment": "Add viewable"},
        )
        assert created.status_code == 201, created.text
        opened = client.post("/api/creo/open", json={"object_id": created.json()["uuid"]})
        assert opened.status_code == 200, opened.text
        assert opened.json()["method"] == "creo_view"
        assert opened.json()["creo_object"] is False
        assert recorder.opened
        assert recorder.opened[0].name == "preview.pvz"


@requires_git
def test_open_include_dependencies_false_skips_neighbors(
    data_dir, repo_parent, identity: StaticUserProvider
):
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "DependenciesFlag"}).json()
        part = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("pin.prt", b"part", "application/octet-stream")},
            data={"comment": "Part"},
        )
        asm = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("arm.asm", b"asm-with-pin.prt", "application/octet-stream")},
            data={"comment": "Asm"},
        )
        assert part.status_code == 201, part.text
        assert asm.status_code == 201, asm.text
        with_deps = client.post(
            "/api/creo/open",
            json={"object_id": asm.json()["uuid"], "launch": False},
        )
        assert with_deps.status_code == 200, with_deps.text
        assert with_deps.json()["dependencies"]
        skipped = client.post(
            "/api/creo/open",
            json={
                "object_id": asm.json()["uuid"],
                "launch": False,
                "include_dependencies": False,
            },
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["dependencies"] == []


@requires_git
def test_open_dependencies_nested_tree_without_where_used(
    data_dir, repo_parent, identity: StaticUserProvider
):
    """Open must pull sub-asms + parts from vault bytes — no Where Used rebuild."""
    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(
        recorder, ctx.objects, ctx.checkouts, ctx.workspaces, metadata=ctx.metadata
    )
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "AutoDependencies"}).json()
        part = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("pin.prt", b"part-bytes", "application/octet-stream")},
            data={"comment": "Part", "relative_path": "Parts/pin.prt"},
        )
        sub = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("sub.asm", b"uses PIN.PRT", "application/octet-stream")},
            data={"comment": "Sub", "relative_path": "CAD/sub.asm"},
        )
        top = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("top.asm", b"uses SUB.ASM", "application/octet-stream")},
            data={"comment": "Top", "relative_path": "CAD/top.asm"},
        )
        assert part.status_code == 201, part.text
        assert sub.status_code == 201, sub.text
        assert top.status_code == 201, top.text

        opened = client.post(
            "/api/creo/open",
            json={"object_id": top.json()["uuid"], "launch": False},
        )
        assert opened.status_code == 200, opened.text
        names = {item["filename"] for item in opened.json()["dependencies"]}
        assert "sub.asm" in names
        assert "pin.prt" in names

        # Open vault-scan must persist the same edges Rebuild Where Used would write.
        with ctx.session_factory() as db:
            product_row = ctx.products.get_product(db, product["uuid"])
            assert ctx.metadata.where_used_index_present(db, product_row.id) is True
            top_levels = ctx.metadata.top_level_assembly_uuids(db, product_row.id)
            assert top.json()["uuid"] in top_levels
            assert sub.json()["uuid"] not in top_levels


@requires_git
def test_open_dependencies_prefer_where_used_db(
    data_dir, repo_parent, identity: StaticUserProvider
):
    """When Where Used edges exist, open must use them (no vault-name scan needed)."""
    from creopdm.constants import DependencyType
    from creopdm.models.dependency import Dependency

    recorder = RecordingConnector()
    ctx = build_context(ConfigManager(), users=identity)
    ctx.creo = recorder
    ctx.creo_service = CreoService(recorder, ctx.objects, ctx.checkouts, ctx.workspaces)
    with TestClient(create_app(ctx)) as client:
        product = client.post("/api/products", json={"name": "DbDependencies"}).json()
        # Bytes intentionally omit member names so a vault scan would find nothing.
        part = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("pin.prt", b"part-only", "application/octet-stream")},
            data={"comment": "Part", "relative_path": "Parts/pin.prt"},
        )
        sub = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("sub.asm", b"opaque-sub", "application/octet-stream")},
            data={"comment": "Sub", "relative_path": "CAD/sub.asm"},
        )
        top = client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": ("top.asm", b"opaque-top", "application/octet-stream")},
            data={"comment": "Top", "relative_path": "CAD/top.asm"},
        )
        assert part.status_code == 201, part.text
        assert sub.status_code == 201, sub.text
        assert top.status_code == 201, top.text

        with ctx.session_factory() as db:
            product_row = ctx.products.get_product(db, product["uuid"])
            objs = {
                row.filename: row
                for row in ctx.objects.list_objects(db, product_row.id)
            }
            db.add_all(
                [
                    Dependency(
                        product_id=objs["top.asm"].product_id,
                        parent_object_id=objs["top.asm"].id,
                        child_object_id=objs["sub.asm"].id,
                        dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
                        quantity=1.0,
                    ),
                    Dependency(
                        product_id=objs["top.asm"].product_id,
                        parent_object_id=objs["sub.asm"].id,
                        child_object_id=objs["pin.prt"].id,
                        dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
                        quantity=1.0,
                    ),
                ]
            )
            db.commit()

        opened = client.post(
            "/api/creo/open",
            json={"object_id": top.json()["uuid"], "launch": False},
        )
        assert opened.status_code == 200, opened.text
        names = {item["filename"] for item in opened.json()["dependencies"]}
        assert names == {"sub.asm", "pin.prt"}
        assert opened.json().get("content_hash")
