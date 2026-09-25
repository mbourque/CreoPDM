from pathlib import Path

from creopdm.utils.classify import extra_cad_set, unique_type_labels
from creopdm.constants import DEFAULT_TYPE_LABELS, SIDEBAR_COLLAPSED_COOKIE
from tests.conftest import requires_git


def test_sidebar_collapse_cookie_is_applied(client):
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="sidebar-collapse-btn"' in home.text
    assert 'class="workspace"' in home.text
    assert "is-sidebar-collapsed" not in home.text

    client.cookies.set(SIDEBAR_COLLAPSED_COOKIE, "1")
    collapsed = client.get("/")
    assert collapsed.status_code == 200
    assert 'class="workspace is-sidebar-collapsed"' in collapsed.text
    assert 'aria-pressed="true"' in collapsed.text

    client.cookies.set(SIDEBAR_COLLAPSED_COOKIE, "0")
    restored = client.get("/")
    assert restored.status_code == 200
    assert "is-sidebar-collapsed" not in restored.text


def test_get_and_update_settings(client, tmp_path):
    response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["creo_open_mode"] == "association"
    assert payload["creo_view_open_mode"] == "association"
    assert payload["workspace_root"]
    assert payload["default_workspace_root"]
    defaults = payload["default_cad_extensions"]
    assert ".m_p" in defaults
    assert ".frm" not in defaults
    assert ".dxf" not in defaults
    assert ".ncl" not in defaults
    assert ".log" not in defaults
    assert ".bin" in defaults
    assert ".mrd" in defaults
    assert ".xpr" in defaults
    assert ".mtl" in defaults
    assert ".rcp" in defaults
    assert ".mbx" in defaults
    assert ".aux" in defaults
    assert ".smt" in defaults
    assert extra_cad_set(payload["cad_extensions"]) == extra_cad_set(defaults)
    assert extra_cad_set(payload["cad_models_extensions"]) == extra_cad_set([".prt", ".asm", ".drw"])
    assert extra_cad_set(payload["default_cad_models_extensions"]) == extra_cad_set([".prt", ".asm", ".drw"])
    assert extra_cad_set(payload["document_extensions"]) == extra_cad_set(payload["default_document_extensions"])
    assert extra_cad_set(payload["document_extensions"]) == extra_cad_set(
        [
            ".pdf",
            ".xps",
            ".doc",
            ".docx",
            ".rtf",
            ".txt",
            ".odt",
            ".xls",
            ".xlsx",
            ".csv",
            ".ppt",
            ".pptx",
            ".pps",
            ".ppsx",
            ".mpp",
            ".vsd",
            ".vsdx",
            ".pub",
            ".one",
            ".html",
            ".htm",
            ".eml",
            ".msg",
            ".psd",
        ]
    )
    assert ".md" not in payload["document_extensions"]
    assert ".png" not in payload["document_extensions"]
    openable = payload["cad_openable_extensions"]
    assert ".ncl" in openable
    assert ".tap" in openable
    assert ".xml" in openable
    assert ".log" in openable
    assert ".lst" in openable
    assert extra_cad_set(openable) == extra_cad_set(payload["default_cad_openable_extensions"])
    assert ".tph" in payload["purgeable_extensions"]
    assert ".prt" in payload["purgeable_extensions"]
    assert extra_cad_set(payload["purgeable_extensions"]) == extra_cad_set(
        payload["default_purgeable_extensions"]
    )
    models = payload["cad_model_extensions"]
    assert ".prt" in models
    assert ".dxf" in models
    assert ".sldprt" in models
    assert ".catpart" in models
    assert ".tmu" not in models
    assert ".tmz" not in models
    assert ".tmu" in defaults
    assert ".tmz" in defaults
    assert ".pvz" in models
    assert ".ol" in models
    assert ".wrl" in models
    assert ".idx" not in models
    assert ".3mf" in models
    assert ".wrl" not in defaults
    assert ".idx" in defaults
    assert extra_cad_set(models) == extra_cad_set(payload["default_cad_model_extensions"])
    assert payload["ignore_patterns"] == payload["default_ignore_patterns"]
    assert "trail.txt*" in payload["ignore_patterns"]
    assert "proimpex.errors" in payload["ignore_patterns"]
    assert "regen_backup_model*.mrd.*" in payload["ignore_patterns"]
    assert "traceback.log" in payload["ignore_patterns"]
    assert "config.pro" in payload["ignore_patterns"]
    assert "creo_parametric_customization.ui" in payload["ignore_patterns"]
    assert ".exe" in payload["ignore_patterns"]
    assert payload["database_url"].startswith("sqlite:///")
    assert payload["default_database_url"].startswith("sqlite:///")
    assert payload["port"] == 0
    assert payload["agent_base_url"] == "http://127.0.0.1:8766"
    assert payload["workspace_poll_interval_ms"] == 5000

    fake_creo = tmp_path / "parametric.exe"
    fake_creo.write_bytes(b"fake")
    fake_view = tmp_path / "pview.exe"
    fake_view.write_bytes(b"fake-view")
    workspace = tmp_path / "MyWorkspace"
    updated = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "creo_executable": str(fake_creo),
            "creo_view_executable": str(fake_view),
            "workspace_root": str(workspace),
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["creo_open_mode"] == "association"
    assert Path(body["creo_executable"]) == fake_creo
    assert Path(body["creo_view_executable"]) == fake_view
    assert Path(body["workspace_root"]) == workspace.resolve()
    assert workspace.is_dir()

    rejected_mode = client.put("/api/settings", json={"creo_open_mode": "executable"})
    assert rejected_mode.status_code == 422, rejected_mode.text

    kept_view = client.put("/api/settings", json={"creo_open_mode": "embedded"})
    assert kept_view.status_code == 200, kept_view.text
    assert Path(kept_view.json()["creo_view_executable"]) == fake_view
    assert Path(kept_view.json()["workspace_root"]) == workspace.resolve()

    embedded = client.put("/api/settings", json={"creo_open_mode": "embedded"})
    assert embedded.status_code == 200, embedded.text
    assert embedded.json()["creo_open_mode"] == "embedded"
    # Saving again must refresh the connector without AttributeError.
    again = client.put("/api/settings", json={"creo_open_mode": "embedded"})
    assert again.status_code == 200, again.text
    restored = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert restored.status_code == 200, restored.text

    stored = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "database_url": "postgresql+psycopg://creopdm@localhost:5432/creopdm",
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["database_url"] == "postgresql+psycopg://creopdm@localhost:5432/creopdm"

    ported = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "port": 8765},
    )
    assert ported.status_code == 200, ported.text
    assert ported.json()["port"] == 8765
    kept_port = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert kept_port.status_code == 200, kept_port.text
    assert kept_port.json()["port"] == 8765
    models_filter = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "cad_models_extensions": [".prt", "ASM"]},
    )
    assert models_filter.status_code == 200, models_filter.text
    assert extra_cad_set(models_filter.json()["cad_models_extensions"]) == extra_cad_set([".prt", ".asm"])
    kept_models = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert extra_cad_set(kept_models.json()["cad_models_extensions"]) == extra_cad_set([".prt", ".asm"])
    docs_filter = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "document_extensions": [".pdf", "DOCX", ".odt"]},
    )
    assert docs_filter.status_code == 200, docs_filter.text
    assert extra_cad_set(docs_filter.json()["document_extensions"]) == extra_cad_set(
        [".pdf", ".docx", ".odt"]
    )
    kept_docs = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert extra_cad_set(kept_docs.json()["document_extensions"]) == extra_cad_set(
        [".pdf", ".docx", ".odt"]
    )
    rejected = client.put("/api/settings", json={"creo_open_mode": "association", "port": 70000})
    assert rejected.status_code == 422, rejected.text
    assert client.get("/api/settings").json()["port"] == 8765

    page = client.get("/settings")
    assert page.status_code == 200
    assert "Embedded Creo Browser" in page.text
    assert "OS file association" in page.text
    assert "Creo Parametric" not in page.text
    assert "Creo View" not in page.text
    assert "~/.local/share/CreoPDM/vaults" in page.text
    assert "Vault folder" in page.text
    assert "Master repository for each project" in page.text
    assert "CreoPDM/workspaces" not in page.text
    assert "Specific application" not in page.text
    assert "Open Creo View with" not in page.text
    assert 'value="embedded"' in page.text
    assert 'value="association"' in page.text
    assert 'value="view"' not in page.text
    assert 'value="executable"' not in page.text
    headings = [
        "Open Creo models with",
        "Workspace",
        "Creo Models",
        "Documents",
        "Creo-openable models",
        "Text files",
        "Non openable CAD data",
        "Numbered saves",
        "File type names",
        "Ignored files",
        "Network",
        "Database",
    ]
    positions = [page.text.find(title) for title in headings]
    assert all(index >= 0 for index in positions)
    assert positions == sorted(positions)
    assert 'name="cad_models_extensions"' in page.text
    assert 'name="document_extensions"' in page.text
    assert 'name="purgeable_extensions"' in page.text
    assert "Comma-separated, with or without the dot." in page.text
    assert "notes.pdf.2" not in page.text
    assert "Default: .pdf, .xps" not in page.text
    assert 'name="port"' in page.text
    assert 'name="agent_base_url"' in page.text
    assert 'name="workspace_poll_interval_ms"' in page.text
    assert 'value="8765"' in page.text
    assert 'name="creo_view_executable"' not in page.text
    assert 'name="creo_executable"' not in page.text
    assert 'href="/settings/types"' in page.text
    assert payload["type_labels"] == unique_type_labels(DEFAULT_TYPE_LABELS)

    types_page = client.get("/settings/types")
    assert types_page.status_code == 200
    assert "File type names" in types_page.text
    assert 'id="type-labels-form"' in types_page.text


@requires_git
def test_cad_extensions_setting_changes_classification(client, repo_parent):
    saved = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "cad_extensions": [".xyz", "ABC"]},
    )
    assert saved.status_code == 200, saved.text
    assert ".xyz" in saved.json()["cad_extensions"]
    assert ".abc" in saved.json()["cad_extensions"]

    location = repo_parent / "CadExt"
    project = client.post(
        "/api/projects",
        json={"name": "Cad Ext"},
    )
    assert project.status_code == 201, project.text
    created = client.post(
        f"/api/projects/{project.json()['uuid']}/objects",
        files={"file": ("blob.xyz", b"cad-ish", "application/octet-stream")},
        data={"comment": "Custom CAD"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["object_type"] == "CAD"
    assert created.json()["relative_path"] == "blob.xyz"


@requires_git
def test_custom_workspace_used_on_checkout(client, repo_parent, tmp_path):
    workspace = tmp_path / "VaultCopies"
    saved = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "workspace_root": str(workspace)},
    )
    assert saved.status_code == 200, saved.text

    location = repo_parent / "WorkspaceProj"
    project = client.post(
        "/api/projects",
        json={"name": "Workspace Proj"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    checked = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert checked.status_code == 200, checked.text
    copied = workspace / project["uuid"] / "shaft.prt"
    assert copied.is_file()
    assert copied.read_bytes() == b"original-content"


def test_vault_data_dir_uses_vaults_subdir(client, data_dir):
    saved = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "workspace_root": str(data_dir)},
    )
    assert saved.status_code == 200, saved.text
    assert Path(saved.json()["workspace_root"]) == (data_dir / "vaults").resolve()
    kept = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert Path(kept.json()["workspace_root"]) == (data_dir / "vaults").resolve()


def test_type_labels_persist_and_keep_when_omitted(client):
    saved = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "type_labels": [
                {"extension": ".prt", "label": "Part file"},
                {"extension": "", "label": "skip me"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["type_labels"] == [{"extension": ".prt", "label": "Part file"}]

    kept = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert kept.status_code == 200, kept.text
    assert kept.json()["type_labels"] == [{"extension": ".prt", "label": "Part file"}]

    types_page = client.get("/settings/types")
    assert types_page.status_code == 200
    assert 'value=".prt"' in types_page.text
    assert 'value="Part file"' in types_page.text

    variants = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "type_labels": [{"extension": ".stp, step; .STEP", "label": "STEP Model"}],
        },
    )
    assert variants.status_code == 200, variants.text
    assert variants.json()["type_labels"] == [{"extension": ".stp, .step", "label": "STEP Model"}]
    assert client.get("/settings/types").text.count('value=".stp, .step"') == 1

    cleared = client.put(
        "/api/settings",
        json={"creo_open_mode": "association", "type_labels": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["type_labels"] == []


@requires_git
def test_type_labels_shown_in_file_list(client, repo_parent):
    saved = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "type_labels": [{"extension": ".prt", "label": "Machined part"}],
        },
    )
    assert saved.status_code == 200, saved.text

    project = client.post("/api/projects", json={"name": "Type Labels"}).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text

    page = client.get(f"/?project={project['uuid']}")
    assert page.status_code == 200
    assert "Machined part" in page.text
    assert 'title="Machined part"' in page.text
    assert "Click to select. Double-click for history." not in page.text

    detail = client.get(f"/projects/{project['uuid']}/objects/{created.json()['uuid']}")
    assert detail.status_code == 200
    assert "Machined part" in detail.text


def test_creo_status_pill_shows_open_mode(client):
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="creo-status"' in home.text
    assert "· OS" in home.text
    embedded = client.put("/api/settings", json={"creo_open_mode": "embedded"})
    assert embedded.status_code == 200, embedded.text
    page = client.get("/settings")
    assert page.status_code == 200
    start = page.text.index('id="creo-status"')
    pill = page.text[start : page.text.index("</span>", start)]
    assert "· Embedded" in pill
    assert "Opens CAD in the Creo session showing this page" in pill
    assert "parametric.exe" not in pill.lower()
    assert "Opens CAD with Creo Parametric" not in pill
    windows = client.put("/api/settings", json={"creo_open_mode": "association"})
    assert windows.status_code == 200, windows.text
    listed = client.get("/")
    assert listed.status_code == 200
    start = listed.text.index('id="creo-status"')
    pill = listed.text[start : listed.text.index("</span>", start)]
    assert "· OS" in pill
    assert "Opens Creo models as a browser download for the OS association" in pill
    script = client.get("/static/js/app.js")
    assert "function syncCreoStatusPill" in script.text
