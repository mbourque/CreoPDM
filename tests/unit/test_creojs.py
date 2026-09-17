from pathlib import Path

from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.creo.windows_connector import locate_creojs_library
from creopdm.utils.identity import StaticUserProvider


def _fake_creo_loadpoint(root: Path) -> tuple[Path, Path]:
    executable = root / "Parametric" / "bin" / "parametric.bat"
    executable.parent.mkdir(parents=True)
    executable.write_text("@echo off\n", encoding="utf-8")
    library = root / "Common Files" / "apps" / "creojs" / "creojsweb" / "creojs.js"
    library.parent.mkdir(parents=True)
    library.write_bytes(b"var CreoJS = {isAvailable: function () { return true; }};\n")
    return executable, library


def test_locate_creojs_library_walks_from_parametric_bat(tmp_path):
    executable, library = _fake_creo_loadpoint(tmp_path / "Creo 13.4.1.0")
    assert locate_creojs_library(executable) == library.resolve()


def test_locate_creojs_library_missing(tmp_path):
    executable = tmp_path / "Parametric" / "bin" / "parametric.bat"
    executable.parent.mkdir(parents=True)
    executable.write_text("@echo off\n", encoding="utf-8")
    assert locate_creojs_library(executable) is None
    assert locate_creojs_library(None) is None


def test_creojs_route_serves_library_from_settings(tmp_path, data_dir, identity: StaticUserProvider):
    executable, library = _fake_creo_loadpoint(tmp_path / "Creo 13.4.1.0")
    manager = ConfigManager()
    settings = manager.load()
    settings.creo.executable = str(executable)
    manager.save(settings)
    ctx = build_context(manager, users=identity)
    with TestClient(create_app(ctx)) as client:
        missing_home = client.get("/")
        assert missing_home.status_code == 200
        assert 'type="text/creojs"' in missing_home.text
        response = client.get("/creojs.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.content == library.read_bytes()


def test_creojs_route_404_without_install(client):
    response = client.get("/creojs.js")
    assert response.status_code == 404
