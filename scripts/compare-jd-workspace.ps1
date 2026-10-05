# Compare John Deere source folder vs CreoPDM-agent workspace (logical names).
# Writes a log you can @-attach for the agent.
#
# Usage (PowerShell, from anywhere):
#   powershell -File c:\dev\pdm-lite\scripts\compare-jd-workspace.ps1
# Optional:
#   -Src 'c:\PTC\XMA3\demos\JohnDeere\John_Deere\John_Deere'
#   -Dst 'c:\Users\micha\AppData\Local\CreoPDM-agent\workspaces\<product-uuid>'
#   -OutLog 'c:\dev\pdm-lite\jd-workspace-compare.log'

param(
  [string]$Src = 'c:\PTC\XMA3\demos\JohnDeere\John_Deere\John_Deere',
  [string]$Dst = 'c:\Users\micha\AppData\Local\CreoPDM-agent\workspaces\38b4735e-a7d0-40f6-af02-f555db314547',
  [string]$OutLog = 'c:\dev\pdm-lite\jd-workspace-compare.log'
)

function Get-LogicalKey([string]$path, [string]$root) {
  $rel = $path.Substring($root.Length).TrimStart('\', '/')
  $rel = $rel -replace '\\', '/'
  # strip Creo .N tip: name.ext.3 -> name.ext
  if ($rel -match '^(.*\.[A-Za-z0-9]+)\.\d+$') { $rel = $Matches[1] }
  return $rel.ToLowerInvariant()
}

$lines = New-Object System.Collections.Generic.List[string]
function L([string]$s) { [void]$lines.Add($s) }

L "JD workspace compare"
L "generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
L "src: $Src"
L "dst: $Dst"
L ""

if (-not (Test-Path -LiteralPath $Src)) {
  L "ERROR: src not found"
  $lines | Set-Content -LiteralPath $OutLog -Encoding utf8
  Write-Host "Wrote $OutLog"
  exit 1
}
if (-not (Test-Path -LiteralPath $Dst)) {
  L "ERROR: dst not found"
  $lines | Set-Content -LiteralPath $OutLog -Encoding utf8
  Write-Host "Wrote $OutLog"
  exit 1
}

$srcRoot = (Resolve-Path -LiteralPath $Src).Path
$dstRoot = (Resolve-Path -LiteralPath $Dst).Path

$srcFiles = Get-ChildItem -LiteralPath $srcRoot -Recurse -File -Force | Where-Object {
  $_.Name -notmatch '^(thumbs\.db|desktop\.ini)$'
}
$dstFiles = Get-ChildItem -LiteralPath $dstRoot -Recurse -File -Force | Where-Object {
  $_.Name -notmatch '^(thumbs\.db|desktop\.ini)$' -and
  $_.FullName -notmatch '[\\/]\.git([\\/]|$)' -and
  $_.FullName -notmatch '[\\/]\.creopdm([\\/]|$)' -and
  $_.Name -ne '.creopdm_cache_index.json'
}

$srcMap = @{}
foreach ($f in $srcFiles) {
  $k = Get-LogicalKey $f.FullName $srcRoot
  if (-not $srcMap.ContainsKey($k)) { $srcMap[$k] = $f.FullName }
}
$dstMap = @{}
foreach ($f in $dstFiles) {
  $k = Get-LogicalKey $f.FullName $dstRoot
  if (-not $dstMap.ContainsKey($k)) { $dstMap[$k] = $f.FullName }
}

$missingInDst = @($srcMap.Keys | Where-Object { -not $dstMap.ContainsKey($_) } | Sort-Object)
$extraInDst = @($dstMap.Keys | Where-Object { -not $srcMap.ContainsKey($_) } | Sort-Object)

L "SRC files (raw): $($srcFiles.Count)"
L "DST files (raw): $($dstFiles.Count)"
L "SRC logical keys: $($srcMap.Count)"
L "DST logical keys: $($dstMap.Count)"
L "Missing in agent (in JD source, not in workspace): $($missingInDst.Count)"
L "Extra in agent (not in JD source): $($extraInDst.Count)"
L ""
L "=== MISSING IN AGENT ==="
if ($missingInDst.Count -eq 0) {
  L "(none)"
} else {
  foreach ($k in $missingInDst) { L $k }
}
L ""
L "=== EXTRA IN AGENT ==="
if ($extraInDst.Count -eq 0) {
  L "(none)"
} else {
  foreach ($k in $extraInDst) { L $k }
}

$lines | Set-Content -LiteralPath $OutLog -Encoding utf8
Write-Host "Wrote $OutLog"
Write-Host "Missing=$($missingInDst.Count) Extra=$($extraInDst.Count)"
