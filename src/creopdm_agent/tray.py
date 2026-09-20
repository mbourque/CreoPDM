"""Windows (and desktop) system-tray UI for the local CreoPDM agent."""

from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from creopdm_agent import __version__
from creopdm_agent.config import AgentConfig
from creopdm_agent.logbuf import LogBuffer, install_log_buffer
from creopdm_agent.logui import open_log_window
from creopdm_agent.server import create_agent_app

logger = logging.getLogger("creopdm_agent")


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


def _message_box(title: str, text: str) -> None:
    """Show status in a *separate* process so OK cannot deadlock the tray menu."""
    if sys.platform != "win32":
        return
    try:
        import subprocess
        import tempfile

        path = Path(tempfile.gettempdir()) / "creopdm-agent-status.txt"
        path.write_text(text, encoding="utf-8")
        title_ps = title.replace("'", "''")
        path_ps = str(path).replace("'", "''")
        cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"$t = Get-Content -Raw -Encoding UTF8 '{path_ps}'; "
            f"[System.Windows.Forms.MessageBox]::Show($t, '{title_ps}', "
            "'OK', 'Information') | Out-Null; "
            f"Remove-Item -LiteralPath '{path_ps}' -Force -ErrorAction SilentlyContinue"
        )
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-WindowStyle",
                "Hidden",
                "-Command",
                cmd,
            ],
            close_fds=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
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

    log_buffer = LogBuffer()
    install_log_buffer(log_buffer)

    settings.ensure_dirs()
    app = create_agent_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
        log_config=None,
    )
    server = uvicorn.Server(config)

    def serve() -> None:
        logger.info(
            "Listening on http://%s:%s (cache %s)",
            settings.host,
            settings.port,
            settings.resolved_root(),
        )
        server.run()

    thread = threading.Thread(target=serve, name="creopdm-agent", daemon=True)
    thread.start()

    url = f"http://{settings.host}:{settings.port}"
    root = settings.resolved_root()

    def _status_lines() -> tuple[bool, str]:
        # Prefer a quick local summary so the menu never feels dead if HTTP stalls.
        lines = [
            "Status: running",
            f"Port: {settings.port}",
            f"Version: {__version__}",
            f"Cache: {root}",
        ]
        if settings.pdm_url:
            lines.append(f"PDM: {settings.pdm_url}")
        try:
            response = httpx.get(f"{url}/health", timeout=0.75)
            data = response.json()
            if response.status_code == 200 and data.get("ok"):
                lines[0] = "Status: OK (HTTP responding)"
                if data.get("local_root"):
                    lines[3] = f"Cache: {data['local_root']}"
                return True, "\n".join(lines)
            lines[0] = f"Status: unexpected HTTP {response.status_code}"
            return False, "\n".join(lines)
        except Exception as exc:
            lines[0] = "Status: tray running (HTTP check failed)"
            lines.append(str(exc))
            return True, "\n".join(lines)

    def on_show_status(icon: object, item: object) -> None:
        # Defer past the tray menu callback — a modal MessageBox here can ignore OK.
        def show() -> None:
            ok, text = _status_lines()
            title = "CreoPDM agent" if ok else "CreoPDM agent — problem"
            try:
                icon.title = f"CreoPDM agent — {'OK' if ok else 'Error'} (:{settings.port})"
            except Exception:
                pass
            _message_box(title, text)

        threading.Timer(0.2, show).start()

    def on_show_logs(icon: object, item: object) -> None:
        open_log_window(log_buffer, title=f"CreoPDM agent log (:{settings.port})")

    def on_open_cache(icon: object, item: object) -> None:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(path.as_uri())

    def on_quit(icon: object, item: object) -> None:
        server.should_exit = True
        logger.info("Stopping agent")
        icon.stop()

    menu = pystray.Menu(
        Item(f"CreoPDM agent {__version__}", None, enabled=False),
        Item(f"Listening on {settings.port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("Show status", on_show_status),
        Item("Show logs", on_show_logs),
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
