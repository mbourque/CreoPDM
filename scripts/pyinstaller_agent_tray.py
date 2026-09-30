"""PyInstaller entry point for a shareable creopdm-agent-tray.exe (no console)."""

from __future__ import annotations

from creopdm_agent.main import run_tray_cli


if __name__ == "__main__":
    run_tray_cli()
