"""Windows (and desktop) system-tray UI for the local CreoPDM agent."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from creopdm_agent import __version__
from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app


def hide_console_window() -> None:
    """Hide the console window Windows attached to this process (SW_HIDE)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        # Keep process from putting text back on a new console.
        devnull = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        return


def _make_icon():
    """Build a simple tray icon without shipping a binary asset."""
    from PIL import Image, ImageDraw

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(32, 96, 160, 255))
    draw.rectangle((18, 22, 46, 42), outline=(240, 248, 255, 255), width=3)
    draw.line((18, 30, 46, 30), fill=(240, 248, 255, 255), width=3)
    return image


def run_tray(settings: AgentConfig) -> int:
    hide_console_window()
    # Uvicorn/logging can attach a console a moment later — hide again.
    threading.Timer(0.4, hide_console_window).start()
    threading.Timer(1.5, hide_console_window).start()
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError as exc:
        raise SystemExit(
            "Tray mode needs pystray and Pillow. Install with:\n"
            "  pip install \"creopdm[agent-tray]\"\n"
            "or: pip install pystray Pillow"
        ) from exc

    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing non-loopback host for tray agent.")

    settings.ensure_dirs()
    app = create_agent_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="critical",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)

    def serve() -> None:
        server.run()

    thread = threading.Thread(target=serve, name="creopdm-agent", daemon=True)
    thread.start()

    url = f"http://{settings.host}:{settings.port}"
    root = settings.resolved_root()

    def on_open_health(icon: object, item: object) -> None:
        webbrowser.open(f"{url}/health")

    def on_open_cache(icon: object, item: object) -> None:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(path.as_uri())

    def on_quit(icon: object, item: object) -> None:
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        Item(f"CreoPDM agent {__version__}", None, enabled=False),
        Item(f"Listening on {settings.port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("Open health page", on_open_health),
        Item("Open cache folder", on_open_cache),
        pystray.Menu.SEPARATOR,
        Item("Quit", on_quit),
    )
    icon = pystray.Icon(
        "creopdm-agent",
        _make_icon(),
        f"CreoPDM agent (:{settings.port})",
        menu,
    )
    icon.run()
    return 0
