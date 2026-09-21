"""Agent settings dialog (WinForms on Windows — no Tcl/Tk)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from creopdm_agent.config import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    DEFAULT_PORT,
    DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    AgentConfig,
    build_pdm_url,
    config_path,
    default_data_dir,
    load_config,
    save_config,
    split_pdm_url,
)

_CREATE_NO_WINDOW = 0x08000000


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _winforms_script(initial: dict[str, object]) -> str:
    payload = json.dumps(initial, ensure_ascii=True)
    path = str(config_path().resolve())
    return f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$initial = ConvertFrom-Json -InputObject {_ps_quote(payload)}
$settingsPath = {_ps_quote(path)}
$form = New-Object System.Windows.Forms.Form
$form.Text = 'CreoPDM agent settings'
$form.Width = 520
$form.Height = 580
$form.MinimumSize = New-Object System.Drawing.Size(460, 500)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$timerTop = New-Object System.Windows.Forms.Timer
$timerTop.Interval = 600
$timerTop.Add_Tick({{ $form.TopMost = $false; $timerTop.Stop() }})
$timerTop.Start()
$panel = New-Object System.Windows.Forms.Panel
$panel.Dock = 'Fill'
$panel.AutoScroll = $true
$panel.Padding = New-Object System.Windows.Forms.Padding(12)
$y = 12
function Add-Label([string]$text) {{
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $text
  $label.AutoSize = $true
  $label.Location = New-Object System.Drawing.Point(12, $script:y)
  $panel.Controls.Add($label)
  $script:y += 20
}}
function Add-Box([string]$value, [int]$width = 460) {{
  $box = New-Object System.Windows.Forms.TextBox
  $box.Text = $value
  $box.Width = $width
  $box.Location = New-Object System.Drawing.Point(12, $script:y)
  $panel.Controls.Add($box)
  $script:y += 28
  return $box
}}
function Add-Note([string]$text) {{
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $text
  $label.AutoSize = $true
  $label.MaximumSize = New-Object System.Drawing.Size(460, 0)
  $label.ForeColor = [System.Drawing.Color]::DimGray
  $label.Location = New-Object System.Drawing.Point(12, $script:y)
  $panel.Controls.Add($label)
  $script:y += ($label.PreferredHeight + 10)
}}
Add-Label 'CreoPDM host / IP'
$pdmHost = Add-Box ([string]$initial.pdm_host)
Add-Note 'Leave blank to use the browser page URL on open. Or set creopdm.local + port (full http://… in host is OK; port below is still applied).'
Add-Label 'CreoPDM port'
$pdmPort = Add-Box ([string]$initial.pdm_port)
Add-Note 'Port from the CreoPDM browser URL (not 0). Leave blank if host already includes :port, or if host is blank.'
$https = New-Object System.Windows.Forms.CheckBox
$https.Text = 'Use HTTPS for CreoPDM'
$https.Checked = [bool]$initial.pdm_https
$https.AutoSize = $true
$https.Location = New-Object System.Drawing.Point(12, $y)
$panel.Controls.Add($https)
$y += 28
Add-Label 'Optional bearer token'
$token = Add-Box ([string]$initial.token)
Add-Note 'Only if CreoPDM requires auth. Leave blank for local installs.'
Add-Label 'Agent listen port (this Creo PC)'
$agentPort = Add-Box ([string]$initial.agent_port)
Add-Note 'Browser calls http://127.0.0.1:<port>. Match CreoPDM → Local Creo agent URL. Restart tray after changing.'
Add-Label 'Local cache folder'
$cache = Add-Box ([string]$initial.local_root)
Add-Note ('Default: ' + [string]$initial.local_root_default)
Add-Label 'Health check interval (seconds)'
$health = Add-Box ([string]$initial.health_interval_seconds)
Add-Note 'How often the tray checks local agent + CreoPDM. 0 = Status menu only. Minimum 5 when enabled.'
Add-Label 'Browser status poll (seconds)'
$statusPoll = Add-Box ([string]$initial.status_poll_interval_seconds)
Add-Note 'How often the CreoPDM page may re-check /health for the status pill. 0 = once on load only. Default 5.'
$buttons = New-Object System.Windows.Forms.Panel
$buttons.Dock = 'Bottom'
$buttons.Height = 48
$save = New-Object System.Windows.Forms.Button
$save.Text = 'Save'
$save.Width = 90
$save.Location = New-Object System.Drawing.Point(300, 10)
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Cancel'
$cancel.Width = 90
$cancel.Location = New-Object System.Drawing.Point(400, 10)
$buttons.Controls.Add($save)
$buttons.Controls.Add($cancel)
$form.Controls.Add($panel)
$form.Controls.Add($buttons)
$form.AcceptButton = $save
$form.CancelButton = $cancel
$cancel.Add_Click({{ $form.DialogResult = [System.Windows.Forms.DialogResult]::Cancel; $form.Close() }})
$save.Add_Click({{
  $portText = $pdmPort.Text.Trim()
  $agentText = $agentPort.Text.Trim()
  $healthText = $health.Text.Trim()
  if ($agentText -notmatch '^\\d+$') {{
    [System.Windows.Forms.MessageBox]::Show('Agent listen port must be a number.', 'CreoPDM agent') | Out-Null
    return
  }}
  $agentN = [int]$agentText
  if ($agentN -lt 1 -or $agentN -gt 65535) {{
    [System.Windows.Forms.MessageBox]::Show('Agent listen port must be 1–65535.', 'CreoPDM agent') | Out-Null
    return
  }}
  if ($healthText -eq '') {{ $healthText = '30' }}
  if ($healthText -notmatch '^\\d+$') {{
    [System.Windows.Forms.MessageBox]::Show('Health interval must be a number (0 to disable).', 'CreoPDM agent') | Out-Null
    return
  }}
  $statusText = $statusPoll.Text.Trim()
  if ($statusText -eq '') {{ $statusText = '5' }}
  if ($statusText -notmatch '^\\d+$') {{
    [System.Windows.Forms.MessageBox]::Show('Browser status poll must be a number (0 to disable).', 'CreoPDM agent') | Out-Null
    return
  }}
  $pdmPortN = 0
  if ($portText -ne '' -and $portText -notmatch '^\\d+$') {{
    [System.Windows.Forms.MessageBox]::Show('CreoPDM port must be a number or blank.', 'CreoPDM agent') | Out-Null
    return
  }}
  if ($portText -match '^\\d+$') {{ $pdmPortN = [int]$portText }}
  $cacheText = $cache.Text.Trim()
  $defaultCache = [string]$initial.local_root_default
  if ($cacheText -eq $defaultCache) {{ $cacheText = '' }}
  $result = [ordered]@{{
    pdm_host = $pdmHost.Text.Trim()
    pdm_port = $pdmPortN
    pdm_https = [bool]$https.Checked
    token = $token.Text
    agent_port = $agentN
    local_root = $cacheText
    health_interval_seconds = [int]$healthText
    status_poll_interval_seconds = [int]$statusText
  }}
  $json = ($result | ConvertTo-Json -Compress)
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($settingsPath, ($json + "`n"), $utf8)
  $okPath = $settingsPath + '.saved'
  [System.IO.File]::WriteAllText($okPath, "1`n", $utf8)
  $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
  $form.Close()
}})
[void]$form.ShowDialog()
"""


def _initial_payload(settings: AgentConfig) -> dict[str, object]:
    host, port, https = split_pdm_url(settings.pdm_url)
    default_root = str((default_data_dir() / "workspaces").resolve())
    configured_root = (settings.local_root or "").strip()
    display_root = configured_root or default_root
    health = settings.health_interval_seconds
    if health is None:
        health = DEFAULT_HEALTH_INTERVAL_SECONDS
    status_poll = settings.status_poll_interval_seconds
    if status_poll is None:
        status_poll = DEFAULT_STATUS_POLL_INTERVAL_SECONDS
    return {
        # Only show host/port when a default CreoPDM URL is actually saved.
        # When blank, materialize uses the page origin (e.g. http://creopdm.local:52113).
        "pdm_host": host,
        "pdm_port": "" if port is None else str(port),
        "pdm_https": bool(https),
        "token": settings.token or "",
        "agent_port": str(settings.port or DEFAULT_PORT),
        "local_root": display_root,
        "local_root_default": default_root,
        "health_interval_seconds": str(health),
        "status_poll_interval_seconds": str(status_poll),
    }


def _apply_dialog_result(raw: dict, *, base: AgentConfig | None = None) -> AgentConfig:
    """Normalize the WinForms JSON (flat dialog fields) into AgentConfig."""
    current = (base or load_config()).model_copy(deep=True)
    if "pdm_host" in raw or "agent_port" in raw:
        host = str(raw.get("pdm_host") or "").strip()
        port_raw = raw.get("pdm_port")
        try:
            port = int(port_raw) if port_raw not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            port = None
        https = bool(raw.get("pdm_https"))
        current.pdm_url = build_pdm_url(host, port, https=https)
        if "token" in raw:
            current.token = str(raw.get("token") or "")
        if "local_root" in raw:
            root = str(raw.get("local_root") or "").strip()
            default_root = str((default_data_dir() / "workspaces").resolve())
            current.local_root = "" if root in {"", default_root} else root
        if "agent_port" in raw:
            current.port = int(raw["agent_port"])
        if "health_interval_seconds" in raw:
            current.health_interval_seconds = int(raw["health_interval_seconds"])
        if "status_poll_interval_seconds" in raw:
            current.status_poll_interval_seconds = int(raw["status_poll_interval_seconds"])
        return AgentConfig.model_validate(current.model_dump())
    return AgentConfig.model_validate(raw)


def _normalize_saved_dialog(base: AgentConfig | None = None) -> bool:
    """If the dialog wrote a .saved marker, convert flat JSON to AgentConfig."""
    path = config_path()
    marker = Path(str(path) + ".saved")
    if not marker.is_file() and path.is_file():
        # Dialog saved but marker missing — still normalize flat shape if present.
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            return False
        if isinstance(raw, dict) and ("pdm_host" in raw or "agent_port" in raw):
            save_config(_apply_dialog_result(raw, base=base))
            return True
        return False
    if not marker.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        marker.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False
    save_config(_apply_dialog_result(raw, base=base))
    return True


def run_settings_winforms(settings: AgentConfig | None = None) -> int:
    """Blocking settings dialog (CLI / --settings)."""
    import subprocess

    current = settings or load_config()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        save_config(current)
    marker = Path(str(path) + ".saved")
    if marker.is_file():
        marker.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _winforms_script(_initial_payload(current)),
        ],
        check=False,
        creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if _normalize_saved_dialog(base=current):
        return 0
    return int(completed.returncode or 0)


def run_settings_tk(settings: AgentConfig | None = None) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    current = settings or load_config()
    payload = _initial_payload(current)
    root = tk.Tk()
    root.title("CreoPDM agent settings")
    root.geometry("480x480")
    try:
        root.attributes("-topmost", True)
        root.after(600, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)
    fields: dict[str, tk.Variable] = {}

    def row(label: str, key: str, value: str, note: str = "") -> None:
        ttk.Label(frame, text=label).pack(anchor=tk.W)
        var = tk.StringVar(value=value)
        fields[key] = var
        ttk.Entry(frame, textvariable=var).pack(fill=tk.X, pady=(0, 4))
        if note:
            ttk.Label(frame, text=note, wraplength=440, foreground="#555").pack(
                anchor=tk.W, pady=(0, 8)
            )

    row(
        "CreoPDM host / IP",
        "pdm_host",
        str(payload["pdm_host"]),
        "Leave blank to use the CreoPDM URL from the browser (recommended).",
    )
    row("CreoPDM port", "pdm_port", str(payload["pdm_port"]))
    https_var = tk.BooleanVar(value=bool(payload["pdm_https"]))
    ttk.Checkbutton(frame, text="Use HTTPS for CreoPDM", variable=https_var).pack(anchor=tk.W)
    row("Optional bearer token", "token", str(payload["token"]))
    row(
        "Agent listen port",
        "agent_port",
        str(payload["agent_port"]),
        "Restart tray after changing. Match CreoPDM Local Creo agent URL.",
    )
    row(
        "Local cache folder",
        "local_root",
        str(payload["local_root"]),
        f"Default: {payload['local_root_default']}",
    )
    row(
        "Health check interval (seconds)",
        "health_interval_seconds",
        str(payload["health_interval_seconds"]),
        "0 = only when opening Status. Minimum 5 when enabled.",
    )
    row(
        "Browser status poll (seconds)",
        "status_poll_interval_seconds",
        str(payload["status_poll_interval_seconds"]),
        "0 = once on load only. How often the CreoPDM page may re-check /health.",
    )

    def save() -> None:
        try:
            port_text = fields["pdm_port"].get().strip()
            pdm_port = int(port_text) if port_text else None
            agent_port = int(fields["agent_port"].get().strip() or str(DEFAULT_PORT))
            health_text = fields["health_interval_seconds"].get().strip() or str(
                DEFAULT_HEALTH_INTERVAL_SECONDS
            )
            health = int(health_text)
            status_text = fields["status_poll_interval_seconds"].get().strip() or str(
                DEFAULT_STATUS_POLL_INTERVAL_SECONDS
            )
            status_poll = int(status_text)
            root_text = fields["local_root"].get().strip()
            default_root = str(payload["local_root_default"])
            updated = AgentConfig(
                host=current.host,
                port=agent_port,
                pdm_url=build_pdm_url(
                    fields["pdm_host"].get(),
                    pdm_port,
                    https=bool(https_var.get()),
                ),
                token=fields["token"].get(),
                local_root="" if root_text in {"", default_root} else root_text,
                health_interval_seconds=health,
                status_poll_interval_seconds=status_poll,
            )
            save_config(updated)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CreoPDM agent", str(exc))
            return
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(buttons, text="Save", command=save).pack(side=tk.RIGHT)
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side=tk.RIGHT, padx=(0, 8))
    root.mainloop()
    return 0


def run_settings(settings: AgentConfig | None = None) -> int:
    if sys.platform == "win32":
        return run_settings_winforms(settings)
    return run_settings_tk(settings)


def open_settings_window(
    settings: AgentConfig | None = None,
    *,
    on_saved: object | None = None,
) -> None:
    """Open settings like the log panel: hidden PowerShell + WinForms (no cmd)."""
    import logging
    import subprocess
    import threading

    logger = logging.getLogger("creopdm_agent")
    # Always load from disk so reopen shows what was saved (not stale tray memory).
    current = load_config()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        save_config(current)
    # If a previous dialog left flat JSON, normalize it before showing.
    _normalize_saved_dialog(base=current)
    current = load_config()
    marker = Path(str(path) + ".saved")
    if marker.is_file():
        marker.unlink(missing_ok=True)

    def launch() -> None:
        saved = False
        if sys.platform == "win32":
            try:
                proc = subprocess.Popen(
                    [
                        "powershell",
                        "-NoProfile",
                        "-STA",
                        "-WindowStyle",
                        "Hidden",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        _winforms_script(_initial_payload(current)),
                    ],
                    close_fds=False,
                    creationflags=_CREATE_NO_WINDOW,
                )
                proc.wait()
                saved = _normalize_saved_dialog(base=current)
                if saved:
                    logger.info("Agent settings saved")
            except Exception:
                logger.exception("Could not open agent settings")
        else:
            completed = subprocess.run(
                [sys.executable, "-m", "creopdm_agent.settingsui"],
                check=False,
                start_new_session=True,
            )
            saved = completed.returncode == 0
        if saved and callable(on_saved):
            try:
                on_saved()
            except Exception:
                logger.exception("Settings saved callback failed")

    threading.Thread(target=launch, name="creopdm-agent-settings", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="creopdm-agent-settings")
    parser.parse_args(argv)
    return run_settings()


if __name__ == "__main__":
    raise SystemExit(main())
