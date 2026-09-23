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
