"""Build Windows GUI launcher: creopdm-agent-tray.exe (no console)."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    scripts = repo / ".venv" / "Scripts"
    if len(sys.argv) > 1:
        scripts = Path(sys.argv[1]).resolve()
    if not scripts.is_dir():
        print(f"Scripts dir not found: {scripts}", file=sys.stderr)
        return 1

    try:
        from pip._vendor.distlib.scripts import ScriptMaker
    except ImportError:
        try:
            from distlib.scripts import ScriptMaker
        except ImportError:
            print("Need pip's distlib. Run: pip install distlib", file=sys.stderr)
            return 1

    # Remove console .cmd so PATH prefers the .exe
    for stale in scripts.glob("creopdm-agent-tray.cmd"):
        stale.unlink(missing_ok=True)

    python = scripts / "python.exe"
    maker = ScriptMaker(str(scripts), str(scripts))
    maker.clobber = True
    maker.set_mode = False
    # Use python.exe here — options={'gui': True} rewrites it to pythonw.exe.
    # Passing pythonw.exe already would become pythonww.exe and fail.
    if python.is_file():
        maker.executable = str(python)
    created = maker.make(
        "creopdm-agent-tray = creopdm_agent.main:run_tray_cli",
        options={"gui": True},
    )
    for path in created:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
