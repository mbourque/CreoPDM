"""Application entrypoint: LAN server and optional browser launch."""

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
from creopdm.exceptions import ConfigurationError
from creopdm.logging_setup import get_logger

logger = get_logger("startup")


def _bind_port(host: str, port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return int(sock.getsockname()[1])


def find_available_port(host: str, preferred: int = 0) -> int:
    """Bind the port from Settings, or let the OS pick one when that setting is 0."""
    try:
        return _bind_port(host, preferred)
    except OSError as exc:
        if preferred:
            raise ConfigurationError(
                f"Port {preferred} is not available on this PC. "
                "Choose a different port in Settings."
            ) from exc
        raise


def lan_addresses() -> list[str]:
    """IPv4 addresses other devices on this network can use to reach this PC."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127.") and address not in found:
                found.append(address)
    except OSError:
        pass
    return found


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--host", help="Bind address (default: 0.0.0.0, reachable on your LAN)")
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
    host = args.host or settings.server.host or "0.0.0.0"
    preferred = settings.server.port if args.port is None else args.port
    port = find_available_port(host, preferred)
    open_browser = settings.ui.open_browser_on_start and not args.no_browser

    app = create_app(ctx)
    local_url = f"http://127.0.0.1:{port}"
    bind_url = f"http://{host}:{port}"
    phone_urls = [f"http://{address}:{port}" for address in lan_addresses()] if host in {"0.0.0.0", "::"} else []
    logger.info("Starting %s %s at %s", APP_NAME, APP_VERSION, bind_url)
    print(f"{APP_NAME} {APP_VERSION}")
    print("Status: Running")
    print(f"This PC: {local_url}")
    for url in phone_urls:
        print(f"Phone:   {url}")
        logger.info("LAN URL %s", url)
    if not phone_urls and host in {"0.0.0.0", "::"}:
        print("Phone:   use this PC's Wi-Fi IPv4 address and the port above")

    if open_browser:
        try:
            webbrowser.open(local_url)
        except Exception:
            logger.exception("Unable to open the default browser")

    uvicorn.run(app, host=host, port=port, log_level="info", log_config=None)


def run() -> None:
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger("creopdm").info("Shutdown requested")
        sys.exit(0)
    except ConfigurationError as exc:
        print(exc.message, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
