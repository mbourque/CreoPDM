from creopdm.config import ConfigManager
from creopdm.constants import APP_NAME, APP_VERSION


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
