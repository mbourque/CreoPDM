"""CLI entry: run the local CreoPDM agent on this Creo workstation."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from creopdm_agent import __version__
from creopdm_agent.config import DEFAULT_PORT, load_config, save_config
from creopdm_agent.server import create_agent_app


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
        "--save-config",
        action="store_true",
        help="Write the resolved settings to the agent config file and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_config()
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
    settings.ensure_dirs()
    if args.save_config:
        save_config(settings)
        print(f"Saved agent config for port {settings.port}")
        return 0
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "Refusing to bind on a non-loopback host. The agent must stay local to Creo.",
            file=sys.stderr,
        )
        return 2
    app = create_agent_app(settings)
    print(
        f"CreoPDM agent {__version__} on http://{settings.host}:{settings.port} "
        f"(files → {settings.resolved_root()})"
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


def run_cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run_cli()
