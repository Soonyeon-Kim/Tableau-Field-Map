# Claude Stop hook: verification gate.
# Runs -Cmd in the project root when the session is about to stop. If it fails,
# the last 40 lines go to stderr and exit 2 sends them back to the model to fix.
# Wire it in .claude/settings.json (Stop). Copy this file to <repo>/.claude/hooks/.
# Messages are ASCII on purpose: Windows PowerShell 5.1 misreads BOM-less UTF-8 scripts.
param([Parameter(Mandatory)][string]$Cmd, [string]$Root)

[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

# ponytail: one fix round per stop. stop_hook_active means the model is already
# continuing because of this gate; let it stop so an unfixable failure cannot loop.
try { $in = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { $in = $null }
if ($in -and $in.stop_hook_active) { exit 0 }

# Script lives in <root>/.claude/hooks/, so the root is two levels up.
if (-not $Root) { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
Set-Location $Root

# Nothing changed in this folder -> nothing to verify.
if (-not (git status --porcelain .)) { exit 0 }

# A venv activated for another project (inherited from the launching shell) would
# hijack `python`; drop it so the command sees this project's or the system Python.
$venv = $env:VIRTUAL_ENV
if ($venv -and -not $venv.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) {
  $env:PATH = ($env:PATH -split ';' | Where-Object { $_ -and -not $_.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) }) -join ';'
  $env:VIRTUAL_ENV = $null
}

$env:PYTHONUTF8 = '1'
$out = cmd /c "$Cmd 2>&1"
if ($LASTEXITCODE -eq 0) { exit 0 }

$tail = ($out | Select-Object -Last 40) -join "`n"
[Console]::Error.WriteLine("VERIFY GATE FAILED: $Cmd (exit $LASTEXITCODE)`nFix the failures below, then finish.`n$tail")
exit 2
