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

- Python 3.12+
- Git on `PATH`
- Windows 10/11 for Creo Parametric / Creo View integration (Linux is fine for the server and development)

## Install from GitHub

Clone [mbourque/CreoPDM](https://github.com/mbourque/CreoPDM), then install into a virtual environment.

### Windows (PowerShell)

Install [Git for Windows](https://git-scm.com/download/win) and [Python 3.12+](https://www.python.org/downloads/) if needed. Use a **normal** PowerShell (not Run as administrator):

```powershell
git clone https://github.com/mbourque/CreoPDM.git
cd CreoPDM
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

### Linux

On Debian/Ubuntu, install Git and the venv package first: `sudo apt install git python3 python3-venv python3-pip`.

```bash
git clone https://github.com/mbourque/CreoPDM.git
cd CreoPDM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
```

`pip install -e ".[dev]"` is an editable install with pytest. To install only the app, without cloning:

```text
pip install "git+https://github.com/mbourque/CreoPDM.git"
```

## Run

Start from the project folder with the venv active (same as `pytest`). On Windows use a **normal** (not Run as administrator) PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
creopdm
```

```bash
source .venv/bin/activate
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
| `--data-dir PATH` | Override the application data directory (`%LOCALAPPDATA%\CreoPDM` on Windows) |

Example when Settings still has a blocked port:

```powershell
python -m creopdm --port 0
```

The console prints the URL to use:

```
CreoPDM 0.1.0
Status: Running
This PC:    http://127.0.0.1:54321
Other PCs:  http://192.168.x.x:54321
```

`This PC` only works in a browser on the machine running CreoPDM. From another computer, open the **Other PCs** URL printed at startup, for example `http://192.168.1.252:52113`.

If that page does not load, the Linux firewall is usually blocking the port. On the Linux host:

```bash
sudo ufw allow 52113/tcp && sudo ufw reload
```

On Fedora/RHEL:

```bash
sudo firewall-cmd --add-port=52113/tcp --permanent && sudo firewall-cmd --reload
```

Then from the other computer, ping that LAN address. If ping works but the browser still fails, both machines must be on the same LAN (not guest/isolated Wi-Fi). Health check: `GET /api/health`

Allow CreoPDM in Windows Firewall if prompted when the server itself runs on Windows.

A saved port that Windows refuses (`WinError 10013`) stops startup. Use `--port 0`, then set Port to **0** (or another free port) in Settings so the next start works without the flag.

## Tests

With the venv active, run `pytest`. Tests use temporary directories. They never touch a real project repository.

## Data location

On Windows, application data lives in `%LOCALAPPDATA%\CreoPDM\`. On Linux, pass `--data-dir ~/.local/share/CreoPDM` (or set `CREOPDM_DATA_DIR`) unless you want the default `~/AppData/Local/CreoPDM`. Git history and working copies live in the per-project workspace under that folder.
