#Requires -Version 5.1
<#
.SYNOPSIS
  Git pull locally + on the CreoPDM host, restart the Linux service, restart the agent tray.

.EXAMPLE
  .\pull-restart.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$SshHost = "michael@creopdm.local"
$RemoteDir = "~/CreoPDM"

function Start-CreoPdmAgentTrayRestart {
  $venvTray = Join-Path $PSScriptRoot ".venv\Scripts\creopdm-agent-tray.exe"
  $tray = if (Test-Path -LiteralPath $venvTray) { $venvTray } else { "creopdm-agent-tray" }
  Write-Host "Restarting tray: $tray --restart"
  Start-Process -FilePath $tray -ArgumentList "--restart"
}

Write-Host "==> Git pull (this PC)"
git pull

Write-Host "==> Git pull + restart creopdm on $SshHost"
ssh $SshHost "cd $RemoteDir && git pull && systemctl --user restart creopdm.service"

Write-Host "==> Restarting agent tray"
Start-CreoPdmAgentTrayRestart

Write-Host "Done."
