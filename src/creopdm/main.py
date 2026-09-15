"""Application entrypoint: localhost server and optional browser launch."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import webbrowser

import uvicorn

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.logging_setup import get_logger

logger = get_logger("startup")


def find_available_port(host: str, preferred: int = 0) -> int:
    """Bind a socket to discover a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, preferred))
        return int(sock.getsockname()[1])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--host", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="TCP port. 0 selects an available port.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser.")
    parser.add_argument("--data-dir", help="Override the application data directory.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.data_dir:
        import os

        os.environ["CREOPDM_DATA_DIR"] = args.data_dir

    config = ConfigManager()
    ctx = build_context(config)
    settings = ctx.settings
    host = args.host or settings.server.host or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost"}:
        logger.warning("Binding to %s; the default is localhost-only", host)
    preferred = settings.server.port if args.port is None else args.port
    port = find_available_port(host, preferred)
    open_browser = settings.ui.open_browser_on_start and not args.no_browser

    app = create_app(ctx)
    url = f"http://{host}:{port}"
    logger.info("Starting %s %s at %s", APP_NAME, APP_VERSION, url)
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"Status: Running")
    print(url)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            logger.exception("Unable to open the default browser")

    uvicorn.run(app, host=host, port=port, log_level="info", log_config=None)


def run() -> None:
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger("creopdm").info("Shutdown requested")
        sys.exit(0)


if __name__ == "__main__":
    run()
