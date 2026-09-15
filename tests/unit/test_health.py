from creopdm.config import AppSettings, ConfigManager
from creopdm.constants import APP_NAME, APP_VERSION, DEFAULT_EXTRA_CAD_EXTENSIONS
from creopdm.utils.classify import extra_cad_set


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["name"] == APP_NAME
    assert payload["version"] == APP_VERSION


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert APP_NAME in text
    assert f"Version {APP_VERSION}" in text
    assert "Status: Running" in text
    assert 'href="/settings"' in text


def test_config_layout(data_dir):
    manager = ConfigManager(data_dir)
    settings = manager.load()
    assert manager.settings_path.exists()
    assert manager.database_dir.exists()
    assert manager.logs_dir.exists()
    assert settings.server.host == "127.0.0.1"
    assert settings.creo.connector == "auto"
    assert extra_cad_set(settings.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert ".m_p" in settings.cad.extra_extensions
    assert ".dat" in settings.cad.extra_extensions
    assert ".sym" in settings.cad.extra_extensions
    assert ".mrd" in settings.cad.extra_extensions
    assert ".xpr" in settings.cad.extra_extensions


def test_previous_cad_defaults_migrate(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.extra_extensions = [".dxf", ".dwg", ".ncl", ".tph", ".nc", ".tap", ".cnc"]
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert ".inf" in loaded.cad.extra_extensions
    assert ".m_p" in loaded.cad.extra_extensions


def test_custom_cad_extensions_are_not_migrated(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.extra_extensions = [".dxf", ".xyz"]
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.extra_extensions) == extra_cad_set([".dxf", ".xyz"])
