from creopdm_agent.main import build_parser, stop_other_agent_processes


def test_agent_parser_accepts_tray_flag():
    args = build_parser().parse_args(["--tray", "--port", "8767"])
    assert args.tray is True
    assert args.port == 8767


def test_agent_parser_accepts_restart_flag():
    args = build_parser().parse_args(["--tray", "--restart"])
    assert args.tray is True
    assert args.restart is True


def test_stop_other_agent_processes_excludes_self(monkeypatch):
    import os

    self_pid = os.getpid()
    signaled: list[int] = []

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = f"{self_pid}\n999001\n"
            stderr = ""

        if cmd and cmd[0] == "taskkill":
            signaled.append(int(cmd[cmd.index("/PID") + 1]))
            return Result()
        return Result()

    monkeypatch.setattr("creopdm_agent.main.sys.platform", "win32")
    monkeypatch.setattr("creopdm_agent.main.subprocess.run", fake_run)
    monkeypatch.setattr("creopdm_agent.main.time.sleep", lambda _s: None)
    stopped = stop_other_agent_processes(exclude_pids={self_pid})
    assert self_pid not in signaled
    assert 999001 in signaled
    assert stopped == 1
