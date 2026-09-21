from creopdm_agent.config import (
    AgentConfig,
    apply_runtime_settings,
    build_pdm_url,
    load_config,
    save_config,
    split_pdm_url,
)


def test_build_and_split_pdm_url():
    assert build_pdm_url("192.168.1.10", 8765) == "http://192.168.1.10:8765"
    assert build_pdm_url("pdm.example", 443, https=True) == "https://pdm.example:443"
    assert build_pdm_url("http://already:9/path") == "http://already:9"
    assert build_pdm_url("http://creopdm.local", 52113) == "http://creopdm.local:52113"
    host, port, https = split_pdm_url("http://192.168.1.10:8765")
    assert host == "192.168.1.10"
    assert port == 8765
    assert https is False


def test_agent_config_health_interval_floor(tmp_path, monkeypatch):
    monkeypatch.setattr("creopdm_agent.config.default_data_dir", lambda: tmp_path)
    settings = AgentConfig(health_interval_seconds=2)
    assert settings.health_interval_seconds == 5
    settings = AgentConfig(health_interval_seconds=0)
    assert settings.health_interval_seconds == 0


def test_agent_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("creopdm_agent.config.default_data_dir", lambda: tmp_path)
    settings = AgentConfig(
        port=8777,
        pdm_url="http://linux-box:8765",
        token="secret",
        health_interval_seconds=45,
    )
    save_config(settings)
    loaded = load_config()
    assert loaded.port == 8777
    assert loaded.pdm_url == "http://linux-box:8765"
    assert loaded.token == "secret"
    assert loaded.health_interval_seconds == 45


def test_apply_runtime_settings_notes_listen_change():
    running = AgentConfig(port=8766, pdm_url="")
    fresh = AgentConfig(port=8777, pdm_url="http://pdm:8765", health_interval_seconds=60)
    notes = apply_runtime_settings(running, fresh)
    assert running.pdm_url == "http://pdm:8765"
    assert running.health_interval_seconds == 60
    assert running.port == 8766  # listen port not swapped live
    assert notes and "8777" in notes[0]


def test_load_flat_settings_dialog_shape(tmp_path, monkeypatch):
    monkeypatch.setattr("creopdm_agent.config.default_data_dir", lambda: tmp_path)
    from creopdm_agent.config import config_path

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"pdm_host":"10.0.0.2","pdm_port":8765,"pdm_https":false,'
        '"agent_port":8766,"token":"","local_root":"","health_interval_seconds":30}\n',
        encoding="utf-8",
    )
    loaded = load_config()
    assert loaded.pdm_url == "http://10.0.0.2:8765"
    assert loaded.port == 8766


def test_settings_initial_payload_fills_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("creopdm_agent.config.default_data_dir", lambda: tmp_path)
    from creopdm_agent.settingsui import _initial_payload

    payload = _initial_payload(AgentConfig())
    assert payload["pdm_host"] == ""
    assert payload["pdm_port"] == ""
    assert payload["agent_port"] == "8766"
    assert payload["health_interval_seconds"] == "30"
    assert payload["status_poll_interval_seconds"] == "0"
    assert payload["local_root"]
    assert payload["local_root_default"] == payload["local_root"]

    saved = _initial_payload(
        AgentConfig(pdm_url="http://creopdm.local:52113", port=8766)
    )
    assert saved["pdm_host"] == "creopdm.local"
    assert saved["pdm_port"] == "52113"
