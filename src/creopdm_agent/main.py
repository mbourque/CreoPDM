"""CLI entry: run the local CreoPDM agent on this Creo workstation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import uvicorn

from creopdm_agent import __version__
from creopdm_agent.config import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    DEFAULT_PORT,
    DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    load_config,
    save_config,
)
from creopdm_agent.server import create_agent_app

# Windows: spawn without attaching a console window.
_CREATE_NO_WINDOW = 0x08000000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creopdm-agent",
        description=(
            "Local helper for Embedded Creo open. Downloads files from CreoPDM "
            "onto this machine so Creo.JS can open them by path."
        ),
    )
    parser.add_argument("--version", action="version", version=f"creopdm-agent {__version__}")
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default 127.0.0.1 — keep local only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Listen port (default {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--pdm-url",
        default=None,
        help="Default CreoPDM base URL (UI also sends the page origin).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Local folder for downloaded workspace files.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional bearer token when CreoPDM requires auth.",
    )
    parser.add_argument(
        "--health-interval",
        type=int,
        default=None,
        help=(
            "Seconds between tray health checks of the local agent and CreoPDM "
            f"(default {DEFAULT_HEALTH_INTERVAL_SECONDS}; 0 = Status menu only)."
        ),
    )
    parser.add_argument(
        "--status-poll-interval",
        type=int,
        default=None,
        help=(
            "Seconds between CreoPDM page /health checks for the status pill "
            f"(default {DEFAULT_STATUS_POLL_INTERVAL_SECONDS}; 0 = once on load)."
        ),
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Write the resolved settings to the agent config file and exit.",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the agent settings dialog and exit.",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run in the system tray (hides the console on Windows).",
    )
    return parser


def _apply_args(settings, args) -> None:
    if args.host is not None:
        settings.host = args.host.strip() or "127.0.0.1"
    if args.port is not None:
        settings.port = int(args.port)
    if args.pdm_url is not None:
        settings.pdm_url = args.pdm_url.strip()
    if args.root is not None:
        settings.local_root = args.root.strip()
    if args.token is not None:
        settings.token = args.token.strip()
    if args.health_interval is not None:
        settings.health_interval_seconds = int(args.health_interval)
    if args.status_poll_interval is not None:
        settings.status_poll_interval_seconds = int(args.status_poll_interval)


def _safe_print(message: str) -> None:
    """pythonw has no stdout; print() can abort the tray before it starts."""
    try:
        stream = sys.stdout
        if stream is None:
            return
        print(message, file=stream)
    except OSError:
        return


def _windows_tray_without_console(argv: list[str] | None) -> bool:
    """If started with python.exe --tray, re-launch via pythonw and exit parent."""
    if sys.platform != "win32":
        return False
    if Path(sys.executable).name.lower() == "pythonw.exe":
        return False
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        return False
    forwarded = list(argv) if argv is not None else list(sys.argv[1:])
    if "--tray" not in forwarded:
        forwarded = ["--tray", *forwarded]
    cmd = [str(pythonw), "-m", "creopdm_agent", *forwarded]
    subprocess.Popen(
        cmd,
        env=os.environ.copy(),
        close_fds=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.tray and _windows_tray_without_console(argv):
        return 0
    settings = load_config()
    _apply_args(settings, args)
    settings.ensure_dirs()
    if args.settings:
        from creopdm_agent.settingsui import run_settings

        return run_settings(settings)
    if args.save_config:
        save_config(settings)
        _safe_print(f"Saved agent config for port {settings.port}")
        return 0
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        try:
            sys.stderr.write(
                "Refusing to bind on a non-loopback host. The agent must stay local to Creo.\n"
            )
        except OSError:
            pass
        return 2
    if args.tray:
        from creopdm_agent.tray import hide_console_window, run_tray

        hide_console_window()
        return run_tray(settings)
    app = create_agent_app(settings)
    _safe_print(
        f"CreoPDM agent {__version__} on http://{settings.host}:{settings.port} "
        f"(files → {settings.resolved_root()})"
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


def run_cli() -> None:
    raise SystemExit(main())


def run_tray_cli() -> None:
    """gui-scripts entry: same as ``creopdm-agent --tray``."""
    from creopdm_agent.tray import hide_console_window

    hide_console_window()
    raise SystemExit(main(["--tray", *sys.argv[1:]]))


if __name__ == "__main__":
    run_cli()
