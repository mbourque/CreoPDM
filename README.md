# CreoPDM

Local-first Product Data Management for PTC Creo Parametric and related engineering files.

Git is used internally for history. You do not need to run Git commands.

## Current milestone

v0.1 is being built in stages. **Milestones 1–4 are implemented:**

1. Local FastAPI application, SQLite, configuration, logging, health page
2. Create / list / open / remove projects with a Git-backed repository
3. Add files, classify them, create PDM objects, and record an initial version
4. Local checkout / check-in locks, workspace files, and Open in Creo

Locks are stored in the local SQLite database (single-workstation). BOM, live Creo scanning, and remote sync are still later work.

## Requirements

- Windows 10/11 (also runs on other platforms for development)
- Python 3.12+
- Git on `PATH`

## Setup

```powershell
cd c:\dev\pdm-lite
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Run

Start from a **normal** (not Run as administrator) PowerShell in the project folder, with the venv active (same as `pytest`):

```powershell
.\.venv\Scripts\Activate.ps1
creopdm
```

That command is on `PATH` from the venv (not a script in the repo, so you do not type `.\creopdm`). It starts the server on port **52113** and does not open a browser, which is the usual setup for Creo's built-in browser.

After `pip install -e .` (or `pip install -e ".[dev]"`), do that install once more if `creopdm` is missing or still ignores those flags.

To start without those defaults, use the module:

```powershell
.\.venv\Scripts\Activate.ps1
python -m creopdm
```

The module form uses the **Port** in Settings (`%LOCALAPPDATA%\CreoPDM\config\settings.json`). **0** (the default) picks a free port each start. A specific value such as `8765` is reused until Windows blocks it.

Command-line flags override Settings for that start only:

| Flag | Meaning |
| --- | --- |
| `--port 0` | Pick a free port this start (use this if the Settings port is blocked and you cannot open the UI) |
| `--port 8765` | Bind that TCP port this start |
| `--host 0.0.0.0` | Bind address (default is all interfaces, so phones on the LAN can connect) |
| `--no-browser` | Do not open the default browser |
| `--data-dir PATH` | Override `%LOCALAPPDATA%\CreoPDM` |

Example when Settings still has a blocked port:

```powershell
python -m creopdm --port 0
```

The console prints the URL to use:

```
CreoPDM 0.1.0
Status: Running
This PC: http://127.0.0.1:54321
Phone:   http://192.168.x.x:54321
```

Allow CreoPDM in Windows Firewall if prompted. Health check: `GET /api/health`

A saved port that Windows refuses (`WinError 10013`) stops startup. Use `--port 0`, then set Port to **0** (or another free port) in Settings so the next start works without the flag.

## Tests

```powershell
pytest
```

Tests use temporary directories. They never touch a real project repository.

## Data location

Application data lives in `%LOCALAPPDATA%\CreoPDM\`. Git history and working copies live in the per-project workspace under that folder.
