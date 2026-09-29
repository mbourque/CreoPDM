from pathlib import Path

from creopdm.config import (
    ConfigManager,
    adopt_legacy_linux_data_dir,
    data_dir_from_environment,
    path_for_settings_display,
)
from creopdm.constants import APP_NAME
from creopdm.services.workspace_service import WorkspaceService


def _posix_home(monkeypatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("creopdm.config.on_windows", lambda: False)
    monkeypatch.setattr("creopdm.config.user_home", lambda: home)
    monkeypatch.delenv("CREOPDM_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)


def test_linux_default_is_xdg(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _posix_home(monkeypatch, home)
    assert data_dir_from_environment() == home / ".local" / "share" / APP_NAME


def test_linux_migrates_appdata_store(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _posix_home(monkeypatch, home)
    legacy = home / "AppData" / "Local" / APP_NAME
    product = legacy / "workspaces" / "proj-1"
    product.mkdir(parents=True)
    (product / "IMG_0809.JPG").write_bytes(b"photo")
    (legacy / "database").mkdir()
    (legacy / "database" / "creopdm.db").write_bytes(b"sqlite")
    xdg = home / ".local" / "share" / APP_NAME
    xdg.mkdir(parents=True)
    (xdg / "config").mkdir()
    found = data_dir_from_environment()
    assert found == xdg
    assert (xdg / "workspaces" / "proj-1" / "IMG_0809.JPG").read_bytes() == b"photo"
    assert (xdg / "database" / "creopdm.db").is_file()
    assert not legacy.exists()


def test_linux_does_not_clobber_used_xdg(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _posix_home(monkeypatch, home)
    legacy = home / "AppData" / "Local" / APP_NAME / "workspaces" / "old"
    legacy.mkdir(parents=True)
    (legacy / "old.txt").write_text("old")
    xdg_share = home / ".local" / "share" / APP_NAME / "workspaces" / "new"
    xdg_share.mkdir(parents=True)
    (xdg_share / "new.txt").write_text("new")
    found = data_dir_from_environment()
    assert found == home / ".local" / "share" / APP_NAME
    assert (xdg_share / "new.txt").read_text() == "new"
    assert (legacy / "old.txt").read_text() == "old"


def test_adopt_is_noop_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("creopdm.config.on_windows", lambda: True)
    target = tmp_path / "keep"
    assert adopt_legacy_linux_data_dir(target) == target


def test_vault_data_dir_normalizes_to_vaults(tmp_path):
    manager = ConfigManager(tmp_path)
    settings = manager.load()
    settings.workspace.root = str(tmp_path)
    assert manager._normalize_workspace_root(settings) is True
    manager.save(settings)
    assert manager.workspace_root() == (tmp_path / "vaults").resolve()


def test_legacy_workspaces_dir_renames_to_vaults(tmp_path):
    legacy = tmp_path / "workspaces" / "proj-1"
    legacy.mkdir(parents=True)
    (legacy / "part.prt").write_bytes(b"prt")
    manager = ConfigManager(tmp_path)
    manager.ensure_layout()
    assert (tmp_path / "vaults" / "proj-1" / "part.prt").read_bytes() == b"prt"
    assert not (tmp_path / "workspaces").exists()
    assert manager.workspace_root() == (tmp_path / "vaults").resolve()


def test_case_insensitive_jpg_lookup(tmp_path):
    stored = tmp_path / "IMG_0809.jpg"
    stored.write_bytes(b"photo")
    found = WorkspaceService._case_insensitive_file(tmp_path / "IMG_0809.JPG")
    assert found.is_file()
    assert found.read_bytes() == b"photo"


def test_path_for_settings_display_uses_tilde_under_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("creopdm.config.user_home", lambda: home)
    vaults = home / ".local" / "share" / APP_NAME / "vaults"
    vaults.mkdir(parents=True)
    assert path_for_settings_display(vaults) == f"~/.local/share/{APP_NAME}/vaults"
    outside = tmp_path / "other" / "vaults"
    outside.mkdir(parents=True)
    assert path_for_settings_display(outside) == str(outside.resolve())


def test_sqlite_url_for_settings_display_hides_login_name(monkeypatch, tmp_path):
    from creopdm.config import sqlite_url_for_settings_display

    home = tmp_path / "home" / "michael"
    home.mkdir(parents=True)
    monkeypatch.setattr("creopdm.config.user_home", lambda: home)
    db_path = home / ".local" / "share" / APP_NAME / "database" / "creopdm.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("x", encoding="utf-8")
    raw = f"sqlite:///{db_path.resolve().as_posix()}"
    shown = sqlite_url_for_settings_display(raw)
    assert "michael" not in shown
    assert shown.startswith("sqlite:///~/")
    assert shown.endswith(f"/{APP_NAME}/database/creopdm.db")
