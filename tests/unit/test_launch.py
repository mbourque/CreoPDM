from pathlib import Path

import os

from creopdm.utils.launch import _powershell_start, open_windows_file, open_windows_folder, working_directory_for


def test_open_windows_file_uses_associated_start(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "Creo Design Guidlines.pdf"
    pdf.write_bytes(b"%PDF")
    started: list[tuple[Path, Path]] = []

    def fake_start(target: Path, workdir: Path) -> None:
        started.append((target, workdir))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    open_windows_file(pdf)
    assert started[0][0] == pdf.resolve()
    assert started[0][1] == tmp_path.resolve()


def test_open_nested_file_uses_parent_folder(tmp_path: Path, monkeypatch):
    nested = tmp_path / "ribbed2"
    nested.mkdir()
    model = nested / "1-inch.xpr"
    model.write_bytes(b"xpr")
    started: list[tuple[Path, Path]] = []

    def fake_start(target: Path, workdir: Path) -> None:
        started.append((target, workdir))

    monkeypatch.setattr("creopdm.utils.launch._start_associated_file", fake_start)
    open_windows_file(model)
    assert started[0][0] == model.resolve()
    assert started[0][1] == nested.resolve()
    assert working_directory_for(model) == nested.resolve()


def test_powershell_start_passes_path_in_env(tmp_path: Path, monkeypatch):
    recorded: dict[str, object] = {}

    def fake_run(args, env=None, **kwargs):
        recorded["args"] = list(args)
        recorded["env_file"] = env.get("CREOPDM_OPEN_FILE") if env else None
        recorded["env_dir"] = env.get("CREOPDM_OPEN_DIR") if env else None
        recorded["command"] = args[-1] if args else ""

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr("creopdm.utils.launch.subprocess.run", fake_run)
    pdf = tmp_path / "Creo Design Guidlines.pdf"
    assert _powershell_start(str(pdf), str(tmp_path)) is True
    assert recorded["env_file"] == str(pdf)
    assert recorded["env_dir"] == str(tmp_path)
    assert "LiteralPath" in str(recorded["command"])
    assert "WorkingDirectory" in str(recorded["command"])
    assert 'start ""' not in str(recorded["command"])


def test_open_windows_folder_uses_explorer(tmp_path: Path, monkeypatch):
    folder = tmp_path / "workspace"
    folder.mkdir()
    recorded: list[list[str]] = []

    def fake_popen(args, **kwargs):
        recorded.append(list(args))

        class Proc:
            pass

        return Proc()

    monkeypatch.setattr("creopdm.utils.launch.subprocess.Popen", fake_popen)
    open_windows_folder(folder)
    assert recorded[0][1] == str(folder.resolve())
    if os.name == "nt":
        assert recorded[0][0] == "explorer.exe"
    else:
        assert recorded[0][0] in {"xdg-open", "open"}
