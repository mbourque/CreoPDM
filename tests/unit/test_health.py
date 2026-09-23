import json
import warnings

from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import AppSettings, ConfigManager
from creopdm.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_CAD_MODELS_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DEFAULT_PURGEABLE_EXTENSIONS,
    DEFAULT_TYPE_LABELS,
    PREVIOUS_DEFAULT_DOCUMENT_SETS,
    PREVIOUS_DEFAULT_EXTRA_CAD_SETS,
)
from creopdm.utils.classify import extra_cad_set, unique_type_labels


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["name"] == APP_NAME
    assert payload["version"] == APP_VERSION


def test_app_js_is_not_cached(client):
    response = client.get("/client/app.js")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert "CREOPDM_STATUS_POLL_V2" in response.text
    assert "status_poll_interval_seconds" in response.text
    assert "pushCreoMetadataForItems" in response.text
    assert "gatherCreoMetadataForFilename" in response.text
    assert "canGatherCreoMetadata" in response.text
    assert "prepareLocalPathForMetadata" in response.text
    assert "#panel-structure .object-open" in response.text
    assert "browseViaAgentPicker" in response.text
    assert "/pick-files" in response.text


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert APP_NAME in text
    assert f"Version {APP_VERSION}" in text
    assert "Status: Running" in text
    assert 'href="/settings"' in text
    assert '<dialog id="busy-overlay"' in text
    assert 'type="text/creojs"' in text
    assert "function setWorkingDirectory" in text
    assert "CREOPDM_ERROR:No project is selected." in text
    assert "creopdm-agent cache when CreoPDM is remote" in text
    assert "session.OpenFile" in text
    assert "pfcModelType.MDL_MFG" in text
    assert "function creoCannotOpenNewerMessage" in text
    assert "function creoOpenFailedMessage" in text
    assert "function creoTryOpenName" in text
    assert "Older Creo versions cannot open it." in text
    assert "CREOPDM_ERROR:" in text
    assert "catch (errAll)" in text
    assert "creoOpenFailedMessage(filename, releaseCatch, \"\", detail)" in text
    assert "throw new Error" not in text.split("function openModel")[1].split("function setWorkingDirectory")[0]
    assert 'id="set-creo-dir-btn"' in text
    assert 'id="add-files-btn"' in text
    assert text.index('id="set-creo-dir-btn"') < text.index('id="add-files-btn"')
    assert 'src="/client/app.js' in text
    assert "push45" in text
    assert "function gatherModelMetadata" in text
    assert "function creoRetrieveForMetadata" in text
    assert "function creoGatherMass" in text
    assert "function creoGatherUnits" in text
    assert "function creoGatherFamilyTable" in text
    assert "function creoGatherBomTree" in text
    assert "function creoGatherFeatures" in text
    assert "feat.GetName" in text
    assert 'id="project-menu-btn"' in text
    assert 'id="sidebar-collapse-btn"' in text
    assert 'class="workspace"' in text
    assert "is-sidebar-collapsed" not in text
    assert "Workspace:" not in text
    assert 'id="checkin-btn"' in text
    assert 'id="creo-status"' in text
    assert "· OS" in text


def test_creo_open_name_cache_stays_with_settings_dir(tmp_path, identity):
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    with TestClient(create_app(build_context(ConfigManager(first_dir), users=identity))) as first:
        changed = first.put("/api/settings", json={"creo_open_mode": "embedded"})
        assert changed.status_code == 200, changed.text
        assert "· Embedded" in first.get("/").text
    with TestClient(create_app(build_context(ConfigManager(second_dir), users=identity))) as second:
        text = second.get("/").text
        start = text.index('id="creo-status"')
        pill = text[start : text.index("</span>", start)]
        assert "· OS" in pill
        assert "· Embedded" not in pill


def test_app_js_strips_creo_error_details(client):
    response = client.get("/static/js/app.js")
    assert response.status_code == 200
    text = response.text
    assert "function userFacingError" in text
    assert r"Uncaught Error:" in text
    assert r"SCRIPT" in text
    assert r"Object\.execute" in text


def test_config_layout(data_dir):
    manager = ConfigManager(data_dir)
    settings = manager.load()
    assert manager.settings_path.exists()
    assert manager.database_dir.exists()
    assert manager.logs_dir.exists()
    assert settings.server.host == "0.0.0.0"
    assert settings.creo.connector == "auto"
    assert settings.creo.open_mode == "association"
    assert settings.creo.view_open_mode == "association"
    assert settings.creo.view_executable is None
    assert extra_cad_set(settings.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert extra_cad_set(settings.cad.openable_extensions) == extra_cad_set(DEFAULT_OPENABLE_CAD_EXTENSIONS)
    assert extra_cad_set(settings.cad.model_extensions) == extra_cad_set(DEFAULT_CREO_MODEL_EXTENSIONS)
    assert extra_cad_set(settings.cad.cad_models_extensions) == extra_cad_set(DEFAULT_CAD_MODELS_EXTENSIONS)
    assert extra_cad_set(settings.cad.document_extensions) == extra_cad_set(DEFAULT_DOCUMENT_EXTENSIONS)
    assert ".m_p" in settings.cad.extra_extensions
    assert ".dat" in settings.cad.extra_extensions
    assert ".sym" in settings.cad.extra_extensions
    assert ".mrd" in settings.cad.extra_extensions
    assert ".xpr" in settings.cad.extra_extensions
    assert ".mtl" in settings.cad.extra_extensions
    assert ".aux" in settings.cad.extra_extensions
    assert ".smt" in settings.cad.extra_extensions
    assert ".ncl" not in settings.cad.extra_extensions
    assert ".log" not in settings.cad.extra_extensions
    assert ".ncl" in settings.cad.openable_extensions
    assert ".tap" in settings.cad.openable_extensions
    assert ".xml" in settings.cad.openable_extensions
    assert ".log" in settings.cad.openable_extensions
    assert ".lst" in settings.cad.openable_extensions
    assert ".dxf" not in settings.cad.extra_extensions
    assert ".frm" not in settings.cad.extra_extensions
    assert ".wrl" not in settings.cad.extra_extensions
    assert ".dxf" in settings.cad.model_extensions
    assert ".tmu" not in settings.cad.model_extensions
    assert ".tmz" not in settings.cad.model_extensions
    assert ".tmu" in settings.cad.extra_extensions
    assert ".tmz" in settings.cad.extra_extensions
    assert ".als" in settings.cad.extra_extensions
    assert ".mac" in settings.cad.extra_extensions
    assert ".xas" in settings.cad.extra_extensions
    assert ".dtl" in settings.cad.extra_extensions
    assert ".tpm" in settings.cad.extra_extensions
    assert ".pvz" in settings.cad.model_extensions
    assert ".ol" in settings.cad.model_extensions
    assert ".wrl" in settings.cad.model_extensions
    assert ".idx" not in settings.cad.model_extensions
    assert ".idx" in settings.cad.extra_extensions
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


def test_remember_folder_is_per_project(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.load()
    manager.remember_folder("proj-a", "Incoming/lib")
    manager.remember_folder("proj-b", "html_tutorials")
    assert manager.remembered_folder("proj-a") == "Incoming/lib"
    assert manager.remembered_folder("proj-b") == "html_tutorials"
    manager.remember_folder("proj-a", "")
    assert manager.remembered_folder("proj-a") == ""
    assert manager.remembered_folder("proj-b") == "html_tutorials"
    manager.forget_project_view("proj-b")
    assert manager.remembered_folder("proj-b") == ""


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


def test_missing_purgeable_extensions_migrate_to_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    manager.save(settings)
    raw_path = manager.settings_path
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw.get("cad", {}).pop("purgeable_extensions", None)
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.purgeable_extensions) == extra_cad_set(
        DEFAULT_PURGEABLE_EXTENSIONS
    )
    assert ".tph" in loaded.cad.purgeable_extensions


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
    assert ".mtl" in loaded.cad.extra_extensions
    assert ".eda" in loaded.cad.extra_extensions
    assert ".spro" in loaded.cad.extra_extensions
    assert ".rcp" in loaded.cad.extra_extensions
    assert ".mbx" in loaded.cad.extra_extensions
    assert ".aux" in loaded.cad.extra_extensions
    assert ".smt" in loaded.cad.extra_extensions
    assert ".tmu" in loaded.cad.extra_extensions
    assert ".tmz" in loaded.cad.extra_extensions
    assert ".als" in loaded.cad.extra_extensions
    assert ".mac" in loaded.cad.extra_extensions
    assert ".xas" in loaded.cad.extra_extensions
    assert ".ncl" in loaded.cad.openable_extensions
    assert ".lst" in loaded.cad.openable_extensions
    assert ".ncl" not in loaded.cad.extra_extensions
    assert ".wrl" not in loaded.cad.extra_extensions
    assert ".idx" in loaded.cad.extra_extensions
    assert ".idx" not in loaded.cad.model_extensions
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


def test_previous_model_defaults_move_tmu_to_extras(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.model_extensions = [*DEFAULT_CREO_MODEL_EXTENSIONS, ".idx", ".tmu", ".tmz"]
    # Prior ship had Design Exploration on models and extras without .tmu/.tmz.
    prior_extras = next(
        item for item in PREVIOUS_DEFAULT_EXTRA_CAD_SETS if ".smt" in item and ".tmu" not in item
    )
    settings.cad.extra_extensions = sorted(prior_extras)
    manager.save(settings)
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.model_extensions) == extra_cad_set(DEFAULT_CREO_MODEL_EXTENSIONS)
    assert extra_cad_set(loaded.cad.extra_extensions) == extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
    assert ".tmu" not in loaded.cad.model_extensions
    assert ".tmz" not in loaded.cad.model_extensions
    assert ".tmu" in loaded.cad.extra_extensions
    assert ".tmz" in loaded.cad.extra_extensions


def test_missing_cad_models_extensions_migrate_to_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    manager.save(settings)
    raw = json.loads(manager.settings_path.read_text(encoding="utf-8"))
    del raw["cad"]["cad_models_extensions"]
    manager.settings_path.write_text(json.dumps(raw), encoding="utf-8")
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.cad_models_extensions) == extra_cad_set(DEFAULT_CAD_MODELS_EXTENSIONS)


def test_missing_document_extensions_migrate_to_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    manager.save(settings)
    raw = json.loads(manager.settings_path.read_text(encoding="utf-8"))
    del raw["cad"]["document_extensions"]
    manager.settings_path.write_text(json.dumps(raw), encoding="utf-8")
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.document_extensions) == extra_cad_set(DEFAULT_DOCUMENT_EXTENSIONS)


def test_previous_document_defaults_shrink_to_office_list(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.document_extensions = sorted(PREVIOUS_DEFAULT_DOCUMENT_SETS[0])
    manager.save(settings)
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.document_extensions) == extra_cad_set(DEFAULT_DOCUMENT_EXTENSIONS)
    assert ".md" not in loaded.cad.document_extensions
    assert ".png" not in loaded.cad.document_extensions
    assert ".psd" in loaded.cad.document_extensions


def test_office_document_defaults_gain_psd(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.document_extensions = sorted(PREVIOUS_DEFAULT_DOCUMENT_SETS[-1])
    manager.save(settings)
    manager._settings = None
    loaded = manager.load()
    assert extra_cad_set(loaded.cad.document_extensions) == extra_cad_set(DEFAULT_DOCUMENT_EXTENSIONS)
    assert ".psd" in loaded.cad.document_extensions


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


def test_pre_companion_type_labels_migrate_to_defaults(tmp_path):
    from creopdm.config import _pre_companion_type_labels

    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.type_labels = unique_type_labels(_pre_companion_type_labels())
    manager.save(settings)
    manager._settings = None
    loaded = manager.load()
    assert unique_type_labels(loaded.cad.type_labels) == unique_type_labels(DEFAULT_TYPE_LABELS)
    assert {"extension": ".mac", "label": "Machine Data"} in loaded.cad.type_labels
    assert {"extension": ".idx, .xas, .xpr", "label": "Instance Accelerator"} in loaded.cad.type_labels


def test_previous_type_labels_gain_new_defaults(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    added = {
        "reviewref.inf",
        ".mrd",
        "mw_settings.xml",
        "mc_error.log",
        ".tmp",
        ".crc",
        ".css, .scss, .sass, .less",
        ".js, .mjs, .cjs, .jsx, .ts, .tsx",
        ".eda",
        ".mcdx",
        ".spro",
        ".rcp",
        ".mbx",
        ".lst",
        ".ncl.tl*",
        ".aux",
        ".cel",
        ".dat",
        ".edm",
        ".inf",
        ".memb",
        ".mtn",
        ".ncd",
        ".nck",
        ".plt",
        ".ppl",
        ".ptd",
        ".shd",
        ".sit",
        ".smt",
        ".docm, .dot, .dotx, .dotm",
        ".odt, .ott, .pages, .wpd",
        ".xlsm, .xlsb, .xlt, .xltx, .xltm",
        ".ods, .numbers",
        ".pptm, .pps, .ppsx, .pot, .potx",
        ".odp, .key",
        ".vsd, .vsdx, .vss, .vstx",
        ".msg, .eml, .oft",
        ".epub, .mobi",
        ".xps, .oxps",
        ".ps",
        ".yaml, .yml",
        ".toml",
        ".markdown, .rst, .adoc",
        ".xhtml, .mhtml",
        ".tsv",
        ".pub",
        ".one, .onepkg",
        ".mpt",
        ".tex, .ltx, .bib",
        ".odg",
        ".psd",
        "trail.txt*",
        ".bom",
        ".m_p",
        ".wrl",
        ".dgm",
        ".mrk",
        ".als",
        ".ref",
        ".tst",
        ".map",
        ".ers",
        ".info",
        ".cbl",
        ".con",
        ".lgh",
        ".mac",
        ".bde",
        ".bdi",
        ".bdm",
        ".ger",
        ".pls",
        ".txa",
    }
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
    assert {"extension": ".crc", "label": "Circular Reference File"} in labels
    assert {"extension": ".css, .scss, .sass, .less", "label": "Stylesheet"} in labels
    assert {"extension": ".js, .mjs, .cjs, .jsx, .ts, .tsx", "label": "JavaScript"} in labels
    assert {"extension": ".eda", "label": "ECAD data"} in labels
    assert {"extension": ".mcdx", "label": "Mathcad"} in labels
    assert {"extension": ".spro", "label": "Creo Flow Analysis"} in labels
    assert {"extension": ".rcp", "label": "Recipe/configuration"} in labels
    assert {"extension": ".mbx", "label": "Toolpath"} in labels
    assert {"extension": ".lst", "label": "Post-list"} in labels
    assert {"extension": ".ncl.tl*", "label": "Intermediate CL File"} in labels
    assert {"extension": ".aux", "label": "Auxiliary Data"} in labels
    assert {"extension": ".cel", "label": "Machine Parameters"} in labels
    assert {"extension": ".dat", "label": "Edit Data"} in labels
    assert {"extension": ".edm", "label": "Contour Parameters"} in labels
    assert {"extension": ".inf", "label": "Information"} in labels
    assert {"extension": ".memb", "label": "Assembly Member"} in labels
    assert {"extension": ".mtn", "label": "Tool Motion"} in labels
    assert {"extension": ".ncd", "label": "CL Alias"} in labels
    assert {"extension": ".nck", "label": "NC Check Image"} in labels
    assert {"extension": ".plt", "label": "Plot"} in labels
    assert {"extension": ".ppl", "label": "Route Sheet"} in labels
    assert {"extension": ".ptd", "label": "Family Table"} in labels
    assert {"extension": ".shd", "label": "Shade Display"} in labels
    assert {"extension": ".sit", "label": "Site Parameters"} in labels
    assert {"extension": ".smt", "label": "Punch Parameters"} in labels
    assert {"extension": ".odt, .ott, .pages, .wpd", "label": "Word Document"} in labels
    assert {"extension": ".vsd, .vsdx, .vss, .vstx", "label": "Visio Drawing"} in labels
    assert {"extension": ".msg, .eml, .oft", "label": "Email"} in labels
    assert {"extension": ".xps, .oxps", "label": "XPS Document"} in labels
    assert {"extension": ".yaml, .yml", "label": "YAML"} in labels
    assert {"extension": ".psd", "label": "Photoshop"} in labels
    assert {"extension": ".als", "label": "Assembly Program"} in labels
    assert {"extension": ".mac", "label": "Machine Data"} in labels
    assert {"extension": ".bom", "label": "BOM"} in labels
    assert {"extension": "trail.txt*", "label": "Trail"} in labels
    assert {"extension": ".idx, .xas, .xpr", "label": "Instance Accelerator"} in labels
