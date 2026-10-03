"""Utilities disk rows: System = volume once; folders = unique directory sizes."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.utilities_service import (
    _directory_size_bytes,
    _directory_usage,
    _volume_usage,
)


def test_directory_usage_is_folder_size_not_volume(tmp_path: Path):
    vaults = tmp_path / "vaults"
    logs = tmp_path / "logs"
    vaults.mkdir()
    logs.mkdir()
    (vaults / "big.bin").write_bytes(b"x" * 4096)
    (logs / "small.log").write_bytes(b"y" * 128)

    system = _volume_usage("System", tmp_path)
    data = _directory_usage("Data directory", tmp_path)
    vault_row = _directory_usage("Vaults", vaults)
    log_row = _directory_usage("Logs", logs)

    assert system.kind == "volume"
    assert system.free_bytes is not None and system.free_bytes > 0
    assert system.used_bytes is not None

    assert data.kind == "directory"
    assert data.free_bytes is None
    assert vault_row.free_bytes is None
    assert log_row.free_bytes is None

    assert vault_row.used_bytes == 4096
    assert log_row.used_bytes == 128
    assert data.used_bytes == _directory_size_bytes(tmp_path)
    assert data.used_bytes >= vault_row.used_bytes + log_row.used_bytes
    # Folder sizes must differ (the old volume-free repeat was useless).
    assert vault_row.used_label != log_row.used_label
    assert vault_row.used_bytes != system.used_bytes or log_row.used_bytes != system.used_bytes
