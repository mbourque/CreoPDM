from creopdm_agent.main import build_parser


def test_agent_parser_accepts_tray_flag():
    args = build_parser().parse_args(["--tray", "--port", "8767"])
    assert args.tray is True
    assert args.port == 8767
