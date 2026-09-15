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

```powershell
python -m creopdm
```

The application binds to `127.0.0.1`, chooses a free port, and opens a browser.

```
CreoPDM
Version 0.1.0
Status: Running
```

Health check: `GET /api/health`

## Tests

```powershell
pytest
```

Tests use temporary directories. They never touch a real project repository.

## Data location

Application data lives in `%LOCALAPPDATA%\CreoPDM\`. Git history and working copies live in the per-project workspace under that folder.
