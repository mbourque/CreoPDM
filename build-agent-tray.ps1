#Requires -Version 5.1
<#
.SYNOPSIS
  Build a shareable one-file creopdm-agent-tray.exe with PyInstaller.

.DESCRIPTION
  Installs agent-tray extras + PyInstaller into the repo venv (if needed), then
  freezes a windowed one-file EXE you can copy to other Windows Creo PCs.

  Output: dist\creopdm-agent-tray.exe

.EXAMPLE
  .\build-agent-tray.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
  Write-Error "Missing $venvPython — create the venv and install the package first."
}

Write-Host "==> Ensuring agent-tray + PyInstaller"
& $venvPython -m pip install -U "pip" "pyinstaller" | Out-Host
& $venvPython -m pip install -e ".[agent-tray]" | Out-Host

$entry = Join-Path $PSScriptRoot "scripts\pyinstaller_agent_tray.py"
$work = Join-Path $PSScriptRoot "build\agent-tray"
$dist = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Force -Path $work | Out-Null
New-Item -ItemType Directory -Force -Path $dist | Out-Null

# Windowed one-file: no console flash; copy dist\creopdm-agent-tray.exe alone.
$pyArgs = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--windowed",
  "--onefile",
  "--name", "creopdm-agent-tray",
  "--distpath", $dist,
  "--workpath", $work,
  "--specpath", $work,
  "--paths", (Join-Path $PSScriptRoot "src"),
  "--collect-submodules", "creopdm_agent",
  "--hidden-import", "uvicorn.logging",
  "--hidden-import", "uvicorn.loops",
  "--hidden-import", "uvicorn.loops.auto",
  "--hidden-import", "uvicorn.protocols",
  "--hidden-import", "uvicorn.protocols.http",
  "--hidden-import", "uvicorn.protocols.http.auto",
  "--hidden-import", "uvicorn.protocols.websockets",
  "--hidden-import", "uvicorn.protocols.websockets.auto",
  "--hidden-import", "uvicorn.lifespan",
  "--hidden-import", "uvicorn.lifespan.on",
  "--hidden-import", "pystray._win32",
  "--hidden-import", "PIL.Image",
  "--hidden-import", "PIL.ImageDraw",
  $entry
)

Write-Host "==> PyInstaller (onefile, windowed)"
& $venvPython @pyArgs
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$exe = Join-Path $dist "creopdm-agent-tray.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  Write-Error "Build finished but $exe was not created."
}

Write-Host ""
Write-Host "Shareable tray ready:"
Write-Host "  $exe"
Write-Host "Copy that file to another Creo PC and run it (no Python/venv required)."
