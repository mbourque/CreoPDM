from pathlib import Path

from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.creo.windows_connector import (
    discover_creojs_library,
    locate_creojs_library,
    resolve_creojs_setting,
)
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


def test_discover_creojs_library_from_env(tmp_path, monkeypatch):
    library = tmp_path / "creojs.js"
    library.write_text("var CreoJS = {};\n", encoding="utf-8")
    monkeypatch.setenv("CREOPDM_CREOJS", str(library))
    assert discover_creojs_library(None) == library.resolve()


def test_discover_creojs_library_from_linux_style_root(tmp_path, monkeypatch):
    monkeypatch.delenv("CREOPDM_CREOJS", raising=False)
    root = tmp_path / "Creo 13.4.1.0"
    executable, library = _fake_creo_loadpoint(root)
    monkeypatch.setenv("CREOPDM_CREO", str(root))
    assert discover_creojs_library(None) == library.resolve()
    assert discover_creojs_library(executable) == library.resolve()


def test_resolve_creojs_setting_accepts_loadpoint(tmp_path):
    root = tmp_path / "Creo 13.4.1.0"
    _executable, library = _fake_creo_loadpoint(root)
    assert resolve_creojs_setting(root) == library.resolve()
    assert resolve_creojs_setting(library) == library.resolve()


def test_settings_creo_js_library_serves_route(tmp_path, data_dir, identity: StaticUserProvider):
    _executable, library = _fake_creo_loadpoint(tmp_path / "Creo 13.4.1.0")
    manager = ConfigManager()
    settings = manager.load()
    settings.creo.js_library = str(library)
    manager.save(settings)
    ctx = build_context(manager, users=identity)
    with TestClient(create_app(ctx)) as client:
        listed = client.get("/api/settings")
        assert listed.status_code == 200
        assert listed.json()["creo_js_library"] == str(library)
        assert listed.json()["creo_js_library_resolved"] == str(library.resolve())
        response = client.get("/creojs.js")
        assert response.status_code == 200
        assert response.content == library.read_bytes()
        page = client.get("/settings")
        assert page.status_code == 200
        assert 'name="creo_js_library"' in page.text


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


def test_creojs_route_serves_bundled_library(client):
    response = client.get("/creojs.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert b"CreoJS" in response.content
