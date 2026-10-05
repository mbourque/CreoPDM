#Requires -Version 5.1
<#
.SYNOPSIS
  Stop creopdm-agent tray, git pull locally + on the CreoPDM host, restart service, start tray.

.EXAMPLE
  .\pull-restart.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$SshHost = "michael@creopdm.local"
$RemoteDir = "~/CreoPDM"

function Stop-CreoPdmAgentTray {
  $stopped = $false
  foreach ($name in @("creopdm-agent-tray", "creopdm-agent")) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
      Write-Host "Stopping process: $name"
      $procs | Stop-Process -Force -ErrorAction SilentlyContinue
      $stopped = $true
    }
  }
  # Tray often runs as pythonw.exe / python.exe with creopdm_agent on the command line.
  $candidates = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -match '^(pythonw?|creopdm-agent|creopdm-agent-tray)' -and
      $_.CommandLine -and
      ($_.CommandLine -match 'creopdm[_-]agent|run_tray')
    }
  foreach ($proc in $candidates) {
    Write-Host "Stopping PID $($proc.ProcessId) ($($proc.Name))"
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    $stopped = $true
  }
  if ($stopped) {
    Start-Sleep -Seconds 1
  } else {
    Write-Host "No agent tray process was running."
  }
}

function Start-CreoPdmAgentTray {
  $venvTray = Join-Path $PSScriptRoot ".venv\Scripts\creopdm-agent-tray.exe"
  $tray = if (Test-Path -LiteralPath $venvTray) { $venvTray } else { "creopdm-agent-tray" }
  Write-Host "Starting tray: $tray"
  Start-Process -FilePath $tray
}

Write-Host "==> Stopping agent tray"
Stop-CreoPdmAgentTray

Write-Host "==> Git pull (this PC)"
git pull

Write-Host "==> Git pull + force-restart creopdm on $SshHost"
# Hung Open / Where Used can leave the worker deaf to SIGTERM; kill then start.
# Never leave the service stopped if pull/pip fails — always attempt start at the end.
$remote = @'
cd ~/CreoPDM || exit 1
git pull || echo "WARN: git pull failed (continuing restart)"
.venv/bin/pip install -e . -q || echo "WARN: pip install failed (continuing restart)"
systemctl --user stop creopdm.service || true
sleep 2
systemctl --user kill -s SIGKILL creopdm.service 2>/dev/null || true
pkill -9 -f '/CreoPDM/.venv/bin/creopdm' 2>/dev/null || true
pkill -9 -f 'uvicorn.*52113' 2>/dev/null || true
# Free the listen port if a stray process still holds it.
fuser -k 52113/tcp 2>/dev/null || true
sleep 1
systemctl --user reset-failed creopdm.service 2>/dev/null || true
systemctl --user start creopdm.service
systemctl --user --no-pager --full status creopdm.service || true
curl -sS -o /dev/null -w "health_http=%{http_code}\n" http://127.0.0.1:52113/health || echo "WARN: /health not responding yet"
'@
ssh $SshHost $remote

Write-Host "==> Starting agent tray"
Start-CreoPdmAgentTray

Write-Host "Done."
