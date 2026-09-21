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
from creopdm_agent.config import (
    AgentConfig,
    apply_runtime_settings,
    default_data_dir,
    load_config,
)
from creopdm_agent.logbuf import LogBuffer, install_log_buffer, uvicorn_log_config
from creopdm_agent.logui import open_log_window
from creopdm_agent.server import create_agent_app
from creopdm_agent.settingsui import open_settings_window

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


def _probe_pdm(pdm_url: str, token: str = "") -> str:
    base = (pdm_url or "").strip().rstrip("/")
    if not base:
        return "PDM: (not set — UI sends page origin on open)"
    headers = {}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        response = httpx.get(f"{base}/api/health", headers=headers, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            name = data.get("name") or data.get("app") or "CreoPDM"
            version = data.get("version") or ""
            label = f"{name} {version}".strip()
            return f"PDM: OK ({label}) @ {base}"
        return f"PDM: HTTP {response.status_code} @ {base}"
    except Exception as exc:
        return f"PDM: unreachable ({exc}) @ {base}"


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
    log_path = default_data_dir() / "logs" / "agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_buffer = LogBuffer(log_path=log_path)
    install_log_buffer(log_buffer)

    app = create_agent_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
        log_config=uvicorn_log_config(),
    )
    server = uvicorn.Server(config)
    stop_health = threading.Event()
    icon_holder: dict[str, object] = {}

    def serve() -> None:
        # dictConfig may replace handlers — keep our buffer attached.
        install_log_buffer(log_buffer)
        logger.info(
            "Listening on http://%s:%s (cache %s)",
            settings.host,
            settings.port,
            settings.resolved_root(),
        )
        if settings.pdm_url:
            logger.info("Default CreoPDM URL %s", settings.pdm_url)
        logger.info(
            "Health interval %ss (0 = Status menu only)",
            settings.health_interval_seconds,
        )
        logger.info("Log file %s", log_path)
        server.run()

    thread = threading.Thread(target=serve, name="creopdm-agent", daemon=True)
    thread.start()

    url = f"http://{settings.host}:{settings.port}"

    def _reload_runtime() -> None:
        try:
            fresh = load_config()
            notes = apply_runtime_settings(settings, fresh)
            for note in notes:
                logger.info("%s", note)
        except Exception:
            logger.exception("Could not reload agent settings")

    def _status_lines() -> tuple[bool, str]:
        _reload_runtime()
        root = settings.resolved_root()
        lines = [
            "Status: running",
            f"Listen: {settings.host}:{settings.port}",
            f"Version: {__version__}",
            f"Cache: {root}",
            f"Health interval: {settings.health_interval_seconds}s",
            f"Browser status poll: {settings.status_poll_interval_seconds}s",
        ]
        lines.append(_probe_pdm(settings.pdm_url, settings.token))
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

    def _update_tooltip(ok: bool, detail: str = "") -> None:
        icon = icon_holder.get("icon")
        if icon is None:
            return
        state = "OK" if ok else "Error"
        title = f"CreoPDM agent — {state} (:{settings.port})"
        if detail:
            title = f"{title} — {detail}"
        try:
            icon.title = title[:120]
        except Exception:
            pass

    def _health_loop() -> None:
        while not stop_health.wait(0.5):
            _reload_runtime()
            interval = int(settings.health_interval_seconds or 0)
            if interval <= 0:
                # Sleep a bit then re-check settings (user may enable interval).
                if stop_health.wait(5):
                    break
                continue
            ok, text = _status_lines()
            pdm_line = next((line for line in text.splitlines() if line.startswith("PDM:")), "")
            detail = ""
            if "PDM: OK" in pdm_line:
                detail = "PDM OK"
            elif "PDM: (not set" in pdm_line:
                detail = "PDM unset"
            elif pdm_line:
                detail = "PDM issue"
            _update_tooltip(ok and ("PDM: OK" in pdm_line or "PDM: (not set" in pdm_line), detail)
            # Wait the configured interval, but wake early on stop.
            stop_health.wait(interval)

    health_thread = threading.Thread(target=_health_loop, name="creopdm-agent-health", daemon=True)
    health_thread.start()

    def on_show_status(icon: object, item: object) -> None:
        # Defer past the tray menu callback — a modal MessageBox here can ignore OK.
        def show() -> None:
            ok, text = _status_lines()
            title = "CreoPDM agent" if ok else "CreoPDM agent — problem"
            _update_tooltip(ok)
            _message_box(title, text)

        threading.Timer(0.2, show).start()

    def on_settings(icon: object, item: object) -> None:
        def after_save() -> None:
            _reload_runtime()
            logger.info(
                "Settings reloaded (PDM %s, health %ss)",
                settings.pdm_url or "(unset)",
                settings.health_interval_seconds,
            )

        open_settings_window(settings, on_saved=after_save)

    def on_show_logs(icon: object, item: object) -> None:
        try:
            open_log_window(log_path, title=f"CreoPDM agent log (:{settings.port})")
        except Exception as exc:
            logger.exception("Could not open log window")
            _message_box(
                "CreoPDM agent log",
                f"Could not open the log window.\n{exc}\n\nLog file:\n{log_path}",
            )

    def on_open_cache(icon: object, item: object) -> None:
        path = Path(settings.resolved_root())
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(path.as_uri())

    def on_quit(icon: object, item: object) -> None:
        stop_health.set()
        server.should_exit = True
        logger.info("Stopping agent")
        icon.stop()

    menu = pystray.Menu(
        Item(f"CreoPDM agent {__version__}", None, enabled=False),
        Item(f"Listening on {settings.port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("Show status", on_show_status),
        Item("Settings…", on_settings),
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
    icon_holder["icon"] = icon
    icon.run()
    stop_health.set()
    return 0
