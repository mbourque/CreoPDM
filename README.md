# CreoPDM

Local-first Product Data Management for PTC Creo Parametric and related engineering files.

Git is used internally for history. You do not need to run Git commands.

## Current milestone

v0.1 is being built in stages. **Milestones 1–4 are implemented:**

1. Local FastAPI application, PostgreSQL (or SQLite), configuration, logging, health page
2. Create / list / open / remove products with a Git-backed repository
3. Add files, classify them, create PDM objects, and record an initial version
4. Local checkout / check-in locks, workspace files, and Open in Creo

Locks are stored in the database. **PostgreSQL is the default for a normal install** (especially the Linux CreoPDM host). SQLite still works if you leave the Database URL blank (single-workstation / quick trials). BOM, live Creo scanning, and remote sync are still later work.

## Requirements

- Python 3.12+
- Git on `PATH`
- Windows 10/11 for Creo Parametric / Creo View integration (Linux is fine for the server and development)
- **PostgreSQL 14+** for a normal CreoPDM server install (see [Database](#database)). The `psycopg` driver is included with CreoPDM. SQLite needs no extra packages if you skip Postgres for local experiments.
- **[CreoPDM Toolkit Companion](https://github.com/mbourque/CreoPDM-Toolkit-Companion)** on every Creo PC that will **Collect** metadata (or Rebuild metadata). Install the Toolkit DLL into Creo via `protk.dat` / `config.pro` — see [Toolkit Companion](#toolkit-companion-creo-pc) below. Without it, Collect cannot read model identity, parameters, features, structure, BOM, and related fields from Creo.

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

On Debian/Ubuntu, install Git, venv, and PostgreSQL first:

```bash
sudo apt install git python3 python3-venv python3-pip postgresql
```

Create the CreoPDM database (once):

```bash
sudo -u postgres psql -c "CREATE USER creopdm WITH PASSWORD 'YOUR_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE \"CreoPDM\" OWNER creopdm;"
```

Then clone and install:

```bash
git clone https://github.com/mbourque/CreoPDM.git
cd CreoPDM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
```

After the first run (or before enabling systemd), set **Settings → Database URL** (or `CREOPDM_DATABASE_URL`) to:

```text
postgresql+psycopg://creopdm:YOUR_PASSWORD@localhost:5432/CreoPDM
```

See [Database](#database) for env-file setup without storing the password in Settings.

`pip install -e ".[dev]"` is an editable install with pytest. To install only the app, without cloning:

```text
pip install "git+https://github.com/mbourque/CreoPDM.git"
```

## Run

Start from the product folder with the venv active (same as `pytest`). On Windows use a **normal** (not Run as administrator) PowerShell:

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
CreoPDM 0.4.0
Status: Running
This PC:    http://127.0.0.1:54321
Other PCs:  http://192.168.x.x:54321
```

`This PC` only works in a browser on the machine running CreoPDM. From another computer, open the **Other PCs** URL printed at startup, for example `http://192.168.1.252:52113`.

**First visit:** if no users exist yet, the browser opens **`/setup`** so you can create the first administrator (no default password). After that, sign in at **`/login`**. See [Users, roles, and product access](docs/users-roles-and-product-access.md).

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
# Hung Open / vault scans ignore a polite stop — kill after a short wait.
TimeoutStopSec=10
KillMode=mixed
KillSignal=SIGTERM
FinalKillSignal=SIGKILL

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now creopdm
systemctl --user status creopdm
```

`creopdm` already binds **52113** and does not open a browser. Git must stay on `PATH` (the unit sets that). On Linux the store is `~/.local/share/CreoPDM` (products, database settings, and `vaults`). Do **not** add `--data-dir` unless you mean a different store.

If an older run used `~/AppData/Local/CreoPDM`, the next start moves that folder into `~/.local/share/CreoPDM` when the new location does not already have products. Restart the service after updating CreoPDM:

```bash
systemctl --user daemon-reload
systemctl --user restart creopdm
```

If **restart hangs** (Chrome cannot load the home page), force-kill then start:

```bash
systemctl --user stop creopdm.service
systemctl --user kill -s SIGKILL creopdm.service
pkill -9 -f '/CreoPDM/.venv/bin/creopdm' || true
systemctl --user reset-failed creopdm.service
systemctl --user start creopdm.service
```

From Windows, `.\pull-restart.ps1` now does that kill/start after `git pull`.

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

Use the agent on the PC using CreoPDM. It downloads CAD into a local workspace so Creo.JS can open files by path, and it **proxies Collect** to the [Toolkit Companion](#toolkit-companion-creo-pc) so CreoPDM can store model metadata.

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

### Shareable tray EXE (no Python on the Creo PC)

On a Windows machine that already has this repo’s venv:

```powershell
.\build-agent-tray.ps1
```

That writes `dist\creopdm-agent-tray.exe` (a real PyInstaller one-file build — not the venv launcher stub under `.venv\Scripts\`).

**Hand to a Creo PC directly:** copy the exe and run it.

**Publish on the CreoPDM server (download from the Agent offline pill):** copy the same file into the host data directory’s `downloads` folder (created on startup):

| Host | Path |
|------|------|
| Linux (default) | `~/.local/share/CreoPDM/downloads/creopdm-agent-tray.exe` |
| Custom `--data-dir` / `CREOPDM_DATA_DIR` | `<data-dir>/downloads/creopdm-agent-tray.exe` |

Example from your Windows build PC (adjust user/host):

```powershell
scp .\dist\creopdm-agent-tray.exe user@creopdm-host:~/.local/share/CreoPDM/downloads/creopdm-agent-tray.exe
```

Then users on Creo see **Creo: Agent offline** in the top bar → click the pill → **Download creopdm-agent-tray.exe** (or start an existing install / set Windows Startup). `./pull-restart.ps1` does **not** publish the exe — copy it after each tray rebuild you want on the server. URL: `/client/agent-tray`.

**Autostart on the Creo PC:** after install, `Win+R` → `shell:startup` → put a shortcut to `creopdm-agent-tray.exe` in that folder so it starts at Windows sign-in.

### Use with Embedded Creo

1. Keep CreoPDM running on the server (for example `systemctl --user` on Linux).
2. Keep `creopdm-agent-tray` running on the Creo PC.
3. Install and load the [Toolkit Companion](#toolkit-companion-creo-pc) in Creo (required for Collect / Rebuild metadata).
4. In CreoPDM Settings, set open mode to **Embedded Creo Browser**.
5. In Creo's built-in browser, open the CreoPDM URL (the Linux **Other PCs** address).
6. Open a model — the page calls the agent at `http://127.0.0.1:8766`, which fetches the file (and assembly dependencies) into the local workspace, then Creo.JS opens native Creo-openable files. SolidWorks / CATIA / Inventor Multi-CAD files are materialized locally; CreoPDM drives **File > Open** in the running session and navigates the dialog to the workspace folder (session working directory is left unchanged).
7. **Set Working Directory** uses the local workspace folder for the current product (not the remote server path).

Quick check that the agent is up: open `http://127.0.0.1:8766/health` in a normal browser on the Creo PC.

## Toolkit Companion (Creo PC)

**Collect**, **Rebuild metadata**, and the Modifications **NEW** outline need [CreoPDM-Toolkit-Companion](https://github.com/mbourque/CreoPDM-Toolkit-Companion) installed into Creo on the same PC as the agent. It is a Pro/TOOLKIT auxiliary app (Windows x64, Creo Parametric **10+**, tested through Creo 13) that runs **inside** Creo — it cannot run standalone — and exposes a small localhost HTTP API (default `http://127.0.0.1:8767`). The same steps are in the in-app help under **Agent tray → Toolkit Companion** (`/help#toolkit`). The companion repo README has the full HTTP API and build notes.

A prebuilt, unlocked `bin\creopdm_structure.dll` is in that repo. You do not need to compile it to use CreoPDM.

**Install**

1. Download or clone [mbourque/CreoPDM-Toolkit-Companion](https://github.com/mbourque/CreoPDM-Toolkit-Companion) and keep these three together in a permanent folder outside Creo’s install (for example `C:\CreoPDM\Toolkit\`):
   - `protk.dat`
   - `bin\creopdm_structure.dll`
   - `text\usascii\creopdm_msg.txt`
2. Edit `protk.dat` so the paths match that folder (the copy in the repo has the author’s paths):

```
NAME        CreoPDMStructure
EXEC_FILE   C:\CreoPDM\Toolkit\bin\creopdm_structure.dll
TEXT_DIR    C:\CreoPDM\Toolkit\text
STARTUP     dll
ALLOW_STOP  TRUE
REVISION    18
END
```

3. Add this line to a `config.pro` Creo reads at startup (startup folder, or `<Creo install>\Common Files\text\config.pro`). Creo accepts more than one `protkdat` line:

```
protkdat C:\CreoPDM\Toolkit\protk.dat
```

4. Restart Creo. `config.pro` is only read at startup. Close Creo before you replace the DLL later (Creo locks it).

**Check**

On startup the message line should say *CreoPDM Structure: HTTP listening on 127.0.0.1.* The app is also listed under Auxiliary Applications. With Creo running:

```powershell
Invoke-RestMethod http://127.0.0.1:8767/health
```

Expect `ok: true` and `service: creopdm-toolkit`. Log: `%TEMP%\creopdm_toolkit.log`.

**Use with CreoPDM**

Keep the tray agent running and Creo open with the companion loaded. Collect, Rebuild metadata, and Modifications NEW ask the **agent** (`127.0.0.1:8766`); the agent asks Toolkit (`127.0.0.1:8767`). Toolkit silent-retrieves a workspace file that is not already in session (no new window). The model does not need to be open for that retrieve. If the message line says HTTP did not start, port 8767 is in use — set `CREOPDM_TOOLKIT_PORT` before Creo starts. “Not unlocked” means the DLL path is wrong or a local rebuild was not unlocked; use the prebuilt DLL.

### How Collect uses the agent and Toolkit

CreoPDM does **not** call Toolkit from the browser or from the Linux server. The chain on the Creo PC is:

1. **CreoPDM UI** (embedded browser) starts Collect / Rebuild metadata for a tip already in the local agent workspace.
2. The page calls the **agent** at `http://127.0.0.1:8766` (`/toolkit/health`, then `/toolkit/snapshot?filename=…&path=…`).
3. The **agent** proxies to Toolkit on `http://127.0.0.1:8767` (`/health`, `/collect?domains=…`, `/open?fileName=…`, `/url?url=…` for main-browser navigation from the navigator pane). Toolkit silent-retrieves the model when needed (no new Creo window/tab), reads identity, parameters, features, structure, BOM, mass, drawings, MFG, and related domains, then returns JSON.
4. The agent maps that JSON into CreoPDM’s metadata snapshot shape and returns it to the page.
5. The page **POSTs** the snapshot to the CreoPDM server so Details / Type / Ask AI / Where Used consumers can use it.

Ports: agent **8766**, Toolkit **8767** (override Toolkit with `CREOPDM_TOOLKIT_PORT` before starting Creo; point the agent at a non-default URL with `CREOPDM_TOOLKIT_URL` or the agent’s `toolkit_base_url` setting).

Open still uses the agent to **materialize** files and Creo.JS / File > Open to bring models into session. Gathering inventory for Collect goes through Toolkit via the agent — keep both the tray agent and Toolkit loaded whenever you Collect.

### Creo navigator embed explorer

Compact list for Creo’s navigator pane (~350–450 px wide): **`/embed/explorer?product=<uuid or name>&file=<tip>&folder=<path>`**. It is a separate page (not the full Files UI). **Open** / **Checkout** / **Details** hand off to Creo’s **main** embedded browser (Creo.JS `SetURL`, or agent→Toolkit `GET /url?url=…` → `ProWindowURLShow`) with `/?product=…&select=…&action=open|checkout` so the normal Files Open chooser runs there — not inside the navigator. No hover thumbnails here (too narrow — they covered names). See [docs/user-interactions.md](docs/user-interactions.md) §18.

## Manage products

**Administration → Manage products** is the hub for product records (separate from the Files list).

| Tile | What it does |
|------|----------------|
| **Edit Products** | Add a product, or change its name, number, and description. The vault folder is fixed after create. |
| **Copy Products** | New product from another product’s current vault files: new id, **A.1**, **In Work**, and a clean Git history (the original is unchanged). **Use hash** locks a UUID as the vault name; uncheck it to type a name with no spaces. |
| **Promote Products** | Change one product’s lifecycle state. Password confirm explains the change from the Lifecycle states matrix. The audit log records **Product state changed**. |
| **Delete products** | Password confirm, then remove that product’s CreoPDM vault and unregister it. Needs `utilities.delete_product`. The old **Utilities → Delete products** address redirects here. |

Copy records **Product copied** in the audit log (not **Product created**). Day-to-day file actions stay on the Files page. See [docs/user-interactions.md](docs/user-interactions.md).

## AI (Ask AI / check-in comments)

CreoPDM can call a local **Ollama** model to draft check-in comments and Modifications “Ask AI” summaries from two revision outlines.

**Shared prompt (paired with a model):**  
[`docs/ai-snapshot-compare-prompt.qwen3-8b-64k.txt`](docs/ai-snapshot-compare-prompt.qwen3-8b-64k.txt)

That file is labeled for **`qwen3-8b-64k:latest`**. To use it on a CreoPDM server:

1. Install/pull that model in Ollama (or another model you prefer — results vary).
2. Open **Administration → System Settings → AI**.
3. Enable AI, set the Ollama host URL and model name (for example `qwen3-8b-64k:latest`).
4. Open the prompt file, copy the prompt body (**omit the `#` header lines** at the top), and paste into **snapshot compare prompt**.
5. Save. Details → Ask AI / Check In → Ask AI for comment use that system prompt with the OLD/NEW outlines CreoPDM builds.

The live prompt lives in server settings (`settings.json`), not in git. The `docs/` file is the hand-out / backup copy for new installs. After the hand-out file changes (for example assembly-constraints rules), re-paste into **snapshot compare prompt** and Save if you want the server to pick up the new wording.

## Tests

With the venv active, run `pytest`. Tests use temporary directories. They never touch a real product repository.

## Data location

On Windows, application data lives in `%LOCALAPPDATA%\CreoPDM\`. On Linux it lives in `~/.local/share/CreoPDM`. Git history and vault copies live in the per-product folder under `vaults` there (older installs used `workspaces`; CreoPDM renames that folder on startup). The Settings vault field should be `~/.local/share/CreoPDM/vaults`, not `~/.local/share/CreoPDM` itself. Pass `--data-dir` or set `CREOPDM_DATA_DIR` only when you want a different store.

## Database

CreoPDM stores products, objects, versions, checkouts, and activity in a SQL database. **Vault files and Git history stay on disk** under `vaults/` — switching databases does not move CAD files.

### PostgreSQL (default for normal installs)

Use this on the Linux CreoPDM host (and any shared server).

**1. Install and create an empty database** (Debian/Ubuntu):

```bash
sudo apt install postgresql
sudo -u postgres psql -c "CREATE USER creopdm WITH PASSWORD 'YOUR_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE \"CreoPDM\" OWNER creopdm;"
```

Use a UTF-8 cluster (Ubuntu defaults are fine). CreoPDM forces `client_encoding=utf8` on connect.

**2. Point CreoPDM at it** — either:

- **Settings → Database URL** (takes effect on the next start), or
- Environment variable **`CREOPDM_DATABASE_URL`** (overrides Settings; preferred on systemd hosts)

```text
postgresql+psycopg://creopdm:PASSWORD@localhost:5432/CreoPDM
```

You can type special characters in the password (for example `@`); CreoPDM encodes them when connecting. Prefer an env file with mode `600` instead of leaving a password in `settings.json`.

**3. Restart CreoPDM** so migrations create the schema:

```bash
systemctl --user restart creopdm.service
journalctl --user -u creopdm -n 40 --no-pager
```

The service should stay **active**. A new empty database starts with no products until you create them (or copy an old SQLite catalog).

**4. Optional — systemd env file** (password not in Settings):

```bash
# Leave Settings Database URL blank only if you are intentionally on SQLite.
# For Postgres via env:
umask 077
cat > ~/.config/creopdm-db.env << 'EOF'
CREOPDM_DATABASE_URL=postgresql+psycopg://creopdm:PASSWORD@localhost:5432/CreoPDM
EOF
chmod 600 ~/.config/creopdm-db.env
```

Add under `[Service]` in `~/.config/systemd/user/creopdm.service`:

```ini
EnvironmentFile=-%h/.config/creopdm-db.env
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user restart creopdm.service
```

### SQLite (optional fallback)

If **Settings → Database URL** is blank and `CREOPDM_DATABASE_URL` is unset, CreoPDM uses a local file:

- Windows: `%LOCALAPPDATA%\CreoPDM\database\creopdm.db`
- Linux: `~/.local/share/CreoPDM/database/creopdm.db`

No extra software is required. Fine for a quick single-PC trial; prefer PostgreSQL for the real server.

Changing the database URL does **not** migrate existing SQLite rows automatically.

### Driver

`pip install -e .` (or `.[dev]`) installs **`psycopg[binary]`**. No system `libpq-dev` package is required for normal Linux/Windows installs.

## Further reading

- [Creo templates and libraries with CreoPDM](docs/creo-library-templates.md) — Library product, Samba share, and `config.pro` UNC paths
- [Linux disk space email alerts](docs/linux-disk-alerts.md) — Hourly disk monitoring with Postfix on the CreoPDM host
