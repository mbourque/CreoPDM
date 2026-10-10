"""Server-published creopdm-agent-tray.exe + Agent offline pill help."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
HELP_TMPL = ROOT / "src" / "creopdm" / "templates" / "help_agent_tray.html"
README = ROOT / "README.md"
DOCS = ROOT / "docs" / "user-interactions.md"


def test_config_downloads_dir_and_tray_path(data_dir):
    from creopdm.config import ConfigManager

    mgr = ConfigManager(data_dir)
    mgr.ensure_layout()
    assert mgr.downloads_dir == data_dir.resolve() / "downloads"
    assert mgr.downloads_dir.is_dir()
    assert mgr.agent_tray_exe_path() == mgr.downloads_dir / "creopdm-agent-tray.exe"
    assert mgr.AGENT_TRAY_DOWNLOAD_NAME == "creopdm-agent-tray.exe"


def test_client_agent_tray_404_when_unpublished(client):
    response = client.get("/client/agent-tray")
    assert response.status_code == 404
    assert "not published" in response.text.lower() or "not published" in str(response.json()).lower()


def test_client_agent_tray_downloads_published_exe(client, data_dir):
    downloads = data_dir / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    exe = downloads / "creopdm-agent-tray.exe"
    exe.write_bytes(b"MZ-fake-tray-bytes")
    response = client.get("/client/agent-tray")
    assert response.status_code == 200, response.text
    assert response.content == b"MZ-fake-tray-bytes"
    disposition = response.headers.get("content-disposition") or ""
    assert "creopdm-agent-tray.exe" in disposition
    assert "attachment" in disposition.lower()


def test_help_agent_tray_page_start_download_autostart(client, data_dir):
    response = client.get("/help/agent-tray")
    assert response.status_code == 200, response.text
    assert "Start it" in response.text
    assert "Download" in response.text
    assert "shell:startup" in response.text
    assert "not published" in response.text.lower() or "does not have" in response.text.lower()
    (data_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (data_dir / "downloads" / "creopdm-agent-tray.exe").write_bytes(b"MZ")
    response = client.get("/help/agent-tray")
    assert response.status_code == 200
    assert 'href="/client/agent-tray"' in response.text
    assert "Download creopdm-agent-tray.exe" in response.text


def test_agent_offline_pill_opens_help():
    script = APP_JS.read_text(encoding="utf-8")
    assert "Creo: Agent offline" in script
    assert "function setCreoStatusPillAgentTrayHelp(" in script
    assert 'dataset.agentTrayHelp = "1"' in script
    assert 'window.open("/help/agent-tray", "creopdm-help")' in script
    help_html = HELP_TMPL.read_text(encoding="utf-8")
    assert "shell:startup" in help_html
    assert "Start it" in help_html
    assert "/client/agent-tray" in help_html


def test_readme_and_docs_cover_publish_and_pill():
    readme = README.read_text(encoding="utf-8")
    assert "downloads/creopdm-agent-tray.exe" in readme
    assert "/client/agent-tray" in readme
    assert "shell:startup" in readme
    docs = DOCS.read_text(encoding="utf-8")
    assert "Creo: Agent offline" in docs
    assert "shell:startup" in docs
