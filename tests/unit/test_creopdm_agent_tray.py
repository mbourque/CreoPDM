from creopdm_agent.main import build_parser


def test_agent_parser_accepts_tray_flag():
    args = build_parser().parse_args(["--tray", "--port", "8767"])
    assert args.tray is True
    assert args.port == 8767


def test_agent_parser_has_no_restart_flag():
    try:
        build_parser().parse_args(["--tray", "--restart"])
        assert False, "expected --restart to be rejected"
    except SystemExit as exc:
        assert exc.code != 0


def test_safe_print_tolerates_missing_stdout(monkeypatch):
    from creopdm_agent.main import _safe_print

    monkeypatch.setattr("creopdm_agent.main.sys.stdout", None)
    _safe_print("should not raise")


def test_tray_parent_spawns_pythonw_from_python_exe(monkeypatch):
    """Console python.exe --tray must hop once to pythonw (then parent exits)."""
    import subprocess
    from pathlib import Path

    from creopdm_agent import main as agent_main

    calls: list[dict] = []

    def fake_popen(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return subprocess.Popen  # unused

    monkeypatch.setattr(agent_main.sys, "platform", "win32")
    monkeypatch.setattr(agent_main.sys, "executable", r"C:\venv\Scripts\python.exe")
    monkeypatch.setattr(agent_main.subprocess, "Popen", fake_popen)
    monkeypatch.delenv(agent_main._TRAY_CHILD_ENV, raising=False)

    real_is_file = Path.is_file

    def fake_is_file(self: Path) -> bool:
        if str(self).lower().endswith("pythonw.exe"):
            return True
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    assert agent_main._windows_tray_without_console(["--tray", "--port", "8767"]) is True
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert cmd[0].lower().endswith("pythonw.exe")
    assert cmd[1:4] == ["-m", "creopdm_agent", "--tray"]
    assert "--port" in cmd and "8767" in cmd
    kwargs = calls[0]["kwargs"]
    assert kwargs["env"][agent_main._TRAY_CHILD_ENV] == "1"
    assert kwargs["creationflags"] == agent_main._CREATE_NO_WINDOW
    assert kwargs["stdout"] is subprocess.DEVNULL


def test_tray_skips_spawn_when_already_pythonw(monkeypatch):
    """Avoid a second hop (that was flashing a second CMD) under pythonw."""
    from creopdm_agent import main as agent_main

    monkeypatch.setattr(agent_main.sys, "platform", "win32")
    monkeypatch.setattr(agent_main.sys, "executable", r"C:\venv\Scripts\pythonw.exe")
    monkeypatch.delenv(agent_main._TRAY_CHILD_ENV, raising=False)
    called = []

    def boom(*args, **kwargs):
        called.append(1)
        raise AssertionError("must not spawn again under pythonw")

    monkeypatch.setattr(agent_main.subprocess, "Popen", boom)
    assert agent_main._windows_tray_without_console(["--tray"]) is False
    assert called == []


def test_tray_child_skips_second_spawn(monkeypatch):
    from creopdm_agent import main as agent_main

    monkeypatch.setattr(agent_main.sys, "platform", "win32")
    monkeypatch.setenv(agent_main._TRAY_CHILD_ENV, "1")
    called = []

    def boom(*args, **kwargs):
        called.append(1)
        raise AssertionError("must not spawn again")

    monkeypatch.setattr(agent_main.subprocess, "Popen", boom)
    assert agent_main._windows_tray_without_console(["--tray"]) is False
    assert called == []
