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
| `--data-dir PATH` | Override the application data directory (`%LOCALAPPDATA%\CreoPDM` on Windows, `~/.local/share/CreoPDM` on Linux) |

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

## Linux systemd service

Run CreoPDM in the background and start it at login (or at boot) with a **user** systemd unit. Stop any `creopdm` you already started in a terminal so port **52113** is free.

Replace `/home/YOU/CreoPDM` if the clone lives somewhere else.

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/creopdm.service << 'EOF'
[Unit]
Description=CreoPDM
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/CreoPDM
Environment=PATH=%h/CreoPDM/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/CreoPDM/.venv/bin/creopdm
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now creopdm
systemctl --user status creopdm
```

`creopdm` already binds **52113** and does not open a browser. Git must stay on `PATH` (the unit sets that). On Linux the store is `~/.local/share/CreoPDM` (projects, SQLite, and `vaults`). Do **not** add `--data-dir` unless you mean a different store.

If an older run used `~/AppData/Local/CreoPDM`, the next start moves that folder into `~/.local/share/CreoPDM` when the new location does not already have projects. Restart the service after updating CreoPDM:

```bash
systemctl --user daemon-reload
systemctl --user restart creopdm
```

Useful commands:

```bash
systemctl --user status creopdm
journalctl --user -u creopdm -f
systemctl --user restart creopdm
systemctl --user stop creopdm
```

The service runs only while you are logged in. To start it at boot without logging in:

```bash
sudo loginctl enable-linger "$USER"
```

Open `http://127.0.0.1:52113` on that PC, or the **Other PCs** LAN URL after allowing the port (see above).

## Creo agent (Windows tray)

Use the agent on the PC using CreoPDM. It downloads CAD into a local cache so Creo.JS can open files by path.

The agent is separate from the CreoPDM server. Do **not** run it on the Linux host for a Windows Creo setup — run it on the PC that runs Creo.

### Install tray extras

With the venv active on the Creo PC:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[agent-tray]"
```

If `pip` fails because `creopdm.exe` is locked, stop any local `creopdm` on that PC and retry. You can also build the tray launcher without reinstalling the main app:

```powershell
.\.venv\Scripts\python.exe scripts\build_agent_tray_launcher.py
```

### Start the tray agent

```powershell
.\.venv\Scripts\Activate.ps1
creopdm-agent-tray
```

That starts in the system tray (no console). Menu items:

- **Show status** — port, version, and cache folder
- **Show logs** — opens a live log window (also written to `%LOCALAPPDATA%\CreoPDM-agent\logs\agent.log`)
- **Open cache folder** — Explorer on the local download cache
- **Quit** — stop the agent

Cache default: `%LOCALAPPDATA%\CreoPDM-agent\workspaces`.

Optional console form (same logs in a terminal instead of the tray window):

```powershell
creopdm-agent
```

Or: `python -m creopdm_agent` / `python -m creopdm_agent --tray`.

### Use with Embedded Creo

1. Keep CreoPDM running on the server (for example `systemctl --user` on Linux).
2. Keep `creopdm-agent-tray` running on the Creo PC.
3. In CreoPDM Settings, set open mode to **Embedded Creo Browser**.
4. In Creo's built-in browser, open the CreoPDM URL (the Linux **Other PCs** address).
5. Open a model — the page calls the agent at `http://127.0.0.1:8766`, which fetches the file (and same-folder assembly companions) into the local cache, then Creo.JS opens native Creo-openable files. SolidWorks / CATIA / Inventor Multi-CAD files are materialized locally; CreoPDM drives **File > Open** in the running session and navigates the dialog to the cache folder (session working directory is left unchanged).
6. **Set Working Directory** uses the agent cache folder for the current project (not the remote server path).

Quick check that the agent is up: open `http://127.0.0.1:8766/health` in a normal browser on the Creo PC.

## Tests

With the venv active, run `pytest`. Tests use temporary directories. They never touch a real project repository.

## Data location

On Windows, application data lives in `%LOCALAPPDATA%\CreoPDM\`. On Linux it lives in `~/.local/share/CreoPDM`. Git history and vault copies live in the per-project folder under `vaults` there (older installs used `workspaces`; CreoPDM renames that folder on startup). The Settings vault field should be `~/.local/share/CreoPDM/vaults`, not `~/.local/share/CreoPDM` itself. Pass `--data-dir` or set `CREOPDM_DATA_DIR` only when you want a different store.

## Further reading

- [Creo templates and libraries with CreoPDM](docs/creo-library-templates.md) — Library project, Samba share, and `config.pro` UNC paths
- [Linux disk space email alerts](docs/linux-disk-alerts.md) — Hourly disk monitoring with Postfix on the CreoPDM host
