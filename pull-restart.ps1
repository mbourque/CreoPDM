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

Write-Host "==> Git pull + restart creopdm on $SshHost"
ssh $SshHost "cd $RemoteDir && git pull && systemctl --user restart creopdm.service"

Write-Host "==> Starting agent tray"
Start-CreoPdmAgentTray

Write-Host "Done."
