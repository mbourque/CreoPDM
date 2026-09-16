import json
import warnings

from creopdm.config import AppSettings, ConfigManager
from creopdm.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DEFAULT_TYPE_LABELS,
    PREVIOUS_DEFAULT_CREO_MODEL_SETS,
)
from creopdm.utils.classify import extra_cad_set, unique_type_labels


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
    assert settings.server.host == "0.0.0.0"
    assert settings.creo.connector == "auto"
    assert extra_cad_set(settings.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert extra_cad_set(settings.cad.openable_extensions) == extra_cad_set(DEFAULT_OPENABLE_CAD_EXTENSIONS)
    assert extra_cad_set(settings.cad.model_extensions) == extra_cad_set(DEFAULT_CREO_MODEL_EXTENSIONS)
    assert ".m_p" in settings.cad.extra_extensions
    assert ".dat" in settings.cad.extra_extensions
    assert ".sym" in settings.cad.extra_extensions
    assert ".mrd" in settings.cad.extra_extensions
    assert ".xpr" in settings.cad.extra_extensions
    assert ".mtl" in settings.cad.extra_extensions
    assert ".ncl" not in settings.cad.extra_extensions
    assert ".log" not in settings.cad.extra_extensions
    assert ".ncl" in settings.cad.openable_extensions
    assert ".tap" in settings.cad.openable_extensions
    assert ".xml" in settings.cad.openable_extensions
    assert ".log" in settings.cad.openable_extensions
    assert ".dxf" not in settings.cad.extra_extensions
    assert ".frm" not in settings.cad.extra_extensions
    assert ".wrl" not in settings.cad.extra_extensions
    assert ".idx" not in settings.cad.extra_extensions
    assert ".dxf" in settings.cad.model_extensions
    assert ".tmu" in settings.cad.model_extensions
    assert ".pvz" in settings.cad.model_extensions
    assert ".tmz" in settings.cad.model_extensions
    assert ".ol" in settings.cad.model_extensions
    assert ".wrl" in settings.cad.model_extensions
    assert ".idx" in settings.cad.model_extensions
    assert ".3mf" in settings.cad.model_extensions
    assert ".x_t" in settings.cad.model_extensions
    assert ".pvz" in settings.cad.model_extensions
    assert settings.ignore.patterns
    assert "trail.txt*" in settings.ignore.patterns
    assert "proimpex.errors" in settings.ignore.patterns
    assert "regen_backup_model*.mrd.*" in settings.ignore.patterns
    assert "traceback.log" in settings.ignore.patterns
    assert "mapkeys.pro" in settings.ignore.patterns
    assert "config.pro" in settings.ignore.patterns
    assert "config.sup" in settings.ignore.patterns
    assert "creo_parametric_customization.ui" in settings.ignore.patterns
    assert settings.database.url == ""
    assert manager.database_url().startswith("sqlite:///")
    assert manager.database_url().endswith("creopdm.db")


def test_database_url_setting_overrides_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("CREOPDM_DATABASE_URL", raising=False)
    manager = ConfigManager(tmp_path / "appdata")
    settings = manager.load()
    settings.database.url = "postgresql+psycopg://creopdm@localhost:5432/creopdm"
    manager.save(settings)
    loaded = ConfigManager(tmp_path / "appdata")
    assert loaded.database_url() == "postgresql+psycopg://creopdm@localhost:5432/creopdm"


def test_database_url_env_overrides_settings(tmp_path, monkeypatch):
    manager = ConfigManager(tmp_path / "appdata")
    settings = manager.load()
    settings.database.url = "postgresql+psycopg://from-file/db"
    manager.save(settings)
    monkeypatch.setenv("CREOPDM_DATABASE_URL", "postgresql+psycopg://from-env/db")
    assert manager.database_url() == "postgresql+psycopg://from-env/db"


def test_previous_localhost_bind_migrates_to_all_interfaces(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.server.host = "127.0.0.1"
    manager.save(settings)
    loaded = manager.load()
    assert loaded.server.host == "0.0.0.0"


def test_previous_cad_defaults_migrate(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.extra_extensions = [".dxf", ".dwg", ".ncl", ".tph", ".nc", ".tap", ".cnc"]
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert extra_cad_set(loaded.cad.openable_extensions) == extra_cad_set(DEFAULT_OPENABLE_CAD_EXTENSIONS)
    assert ".inf" in loaded.cad.extra_extensions
    assert ".m_p" in loaded.cad.extra_extensions
    assert ".ncl" in loaded.cad.openable_extensions
    assert ".ncl" not in loaded.cad.extra_extensions
    assert ".wrl" not in loaded.cad.extra_extensions
    assert ".idx" not in loaded.cad.extra_extensions
    assert extra_cad_set(loaded.cad.model_extensions) == extra_cad_set(DEFAULT_CREO_MODEL_EXTENSIONS)


def test_custom_cad_extensions_are_not_migrated(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.extra_extensions = [".dxf", ".xyz"]
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.extra_extensions) == extra_cad_set([".xyz"])
    assert ".dxf" in loaded.cad.model_extensions


def test_previous_ignore_defaults_migrate(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.ignore.patterns = [
        "*.tst",
        "*.err",
        "*.acl",
        "trail.txt*",
        "std.out",
        "std.err",
        "proimpex.errors",
    ]
    manager.save(settings)
    loaded = manager.load()
    assert loaded.ignore.patterns == list(DEFAULT_IGNORE_PATTERNS)
    assert "regen_backup_model*.mrd.*" in loaded.ignore.patterns
    assert "traceback.log" in loaded.ignore.patterns
    assert "config.pro" in loaded.ignore.patterns
    assert ".exe" in loaded.ignore.patterns


def test_custom_ignore_patterns_are_not_migrated(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.ignore.patterns = ["*.tst", "scratch.tmp"]
    manager.save(settings)
    loaded = manager.load()
    assert loaded.ignore.patterns == ["*.tst", "scratch.tmp"]


def test_previous_model_defaults_migrate(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.model_extensions = list(next(iter(PREVIOUS_DEFAULT_CREO_MODEL_SETS)))
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.model_extensions) == extra_cad_set(DEFAULT_CREO_MODEL_EXTENSIONS)
    assert ".tmu" in loaded.cad.model_extensions
    assert ".pvz" in loaded.cad.model_extensions
    assert ".tmz" in loaded.cad.model_extensions
    assert ".wrl" in loaded.cad.model_extensions
    assert ".idx" in loaded.cad.model_extensions


def test_custom_model_extensions_are_not_migrated(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.model_extensions = [".prt", ".xyz"]
    manager.save(settings)
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.model_extensions) == extra_cad_set([".prt", ".xyz"])
    assert ".tmu" not in loaded.cad.model_extensions
    assert ".pvz" not in loaded.cad.model_extensions
    assert ".wrl" not in loaded.cad.model_extensions


def test_app_settings_dump_has_no_pydantic_serializer_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        AppSettings().model_dump()
    serializer = [item for item in caught if "Pydantic serializer" in str(item.message)]
    assert serializer == []


def test_empty_type_labels_migrate_to_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.type_labels = []
    manager.save(settings)
    loaded = manager.load()
    assert unique_type_labels(loaded.cad.type_labels) == unique_type_labels(DEFAULT_TYPE_LABELS)


def test_missing_type_labels_migrate_to_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    manager.save(settings)
    raw = json.loads(manager.settings_path.read_text(encoding="utf-8"))
    del raw["cad"]["type_labels"]
    manager.settings_path.write_text(json.dumps(raw), encoding="utf-8")
    manager._settings = None
    loaded = manager.load()
    assert unique_type_labels(loaded.cad.type_labels) == unique_type_labels(DEFAULT_TYPE_LABELS)


def test_custom_type_labels_are_not_migrated(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.type_labels = [{"extension": ".prt", "label": "Custom Part"}]
    manager.save(settings)
    loaded = manager.load()
    assert unique_type_labels(loaded.cad.type_labels) == [
        {"extension": ".prt", "label": "Custom Part"}
    ]


def test_previous_type_labels_gain_new_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    added = {"reviewref.inf", ".mrd", "mw_settings.xml", "mc_error.log", ".tmp"}
    settings = AppSettings()
    settings.cad.type_labels = [
        item
        for item in unique_type_labels(DEFAULT_TYPE_LABELS)
        if item["extension"] not in added
    ]
    manager.save(settings)
    manager._settings = None
    loaded = manager.load()
    labels = unique_type_labels(loaded.cad.type_labels)
    assert labels == unique_type_labels(DEFAULT_TYPE_LABELS)
    assert {"extension": "reviewref.inf", "label": "Reference Info"} in labels
    assert {"extension": ".mrd", "label": "Material Removal Data"} in labels
    assert {"extension": "mw_settings.xml", "label": "Module Works Settings"} in labels
    assert {"extension": "mc_error.log", "label": "ModelCHECK Error Log"} in labels
    assert {"extension": ".tmp", "label": "Temp File"} in labels
