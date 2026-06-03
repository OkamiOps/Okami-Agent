# Okami Agent - installer for Windows (PowerShell). ASCII-only on purpose:
# PowerShell 5.1 reads a BOM-less .ps1 as ANSI, so non-ASCII would corrupt parsing when run as a file.
#   irm https://raw.githubusercontent.com/<owner>/okami-agent/main/scripts/install.ps1 | iex
# or, inside the repo:  .\scripts\install.ps1
#
# Creates the venv in a SHORT path (avoids the Windows 260-char limit when the repo lives in
# OneDrive - litellm has long paths). Default: C:\okv  (override with -VenvPath).
[CmdletBinding()]
param(
  [string]$VenvPath = $(if ($env:OKAMI_VENV) { $env:OKAMI_VENV } else { 'C:\okv' }),
  [string]$RepoUrl  = $(if ($env:OKAMI_REPO) { $env:OKAMI_REPO } else { 'https://github.com/okami-agent/okami-agent.git' }),
  [string]$Dest     = $(if ($env:OKAMI_HOME) { $env:OKAMI_HOME } else { "$HOME\.okami-agent" })
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "[ok] $m" -ForegroundColor Green }
function Die($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

# 1) Python 3.11+
$py = $null
foreach ($c in @('python','python3','py')) {
  try {
    $v = & $c -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>$null
    if ($v -and [version]$v -ge [version]'3.11') { $py = $c; break }
  } catch {}
}
if (-not $py) { Die "need Python 3.11+ (install from python.org and reopen PowerShell)." }
Ok "Python: $(& $py --version)"

# 2) Code (local repo OR clone)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($scriptDir -and (Test-Path (Join-Path $scriptDir '..\pyproject.toml'))) {
  $Dest = (Resolve-Path (Join-Path $scriptDir '..')).Path; Say "using local repo at $Dest"
} elseif (Test-Path (Join-Path $Dest '.git')) {
  Say "updating $Dest"; git -C $Dest pull --ff-only 2>$null
} else {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required to clone." }
  Say "cloning into $Dest"; git clone --depth 1 $RepoUrl $Dest
}

# 3) venv (short path) + install
Say "creating venv at $VenvPath and installing..."
& $py -m venv $VenvPath
$pyv = Join-Path $VenvPath 'Scripts\python.exe'
& $pyv -m pip install --quiet --upgrade pip
& $pyv -m pip install --quiet -e $Dest
Ok "Okami installed ($(& (Join-Path $VenvPath 'Scripts\okami.exe') version 2>$null))"

# 4) global `okami` command (shim in the user's WindowsApps dir, which is on PATH)
$shimDir = Join-Path $env:USERPROFILE 'AppData\Local\Microsoft\WindowsApps'
if (-not (Test-Path $shimDir)) { $shimDir = $VenvPath }
$shim = Join-Path $shimDir 'okami.cmd'
$exe = Join-Path $VenvPath 'Scripts\okami.exe'
$cmd = '@echo off' + "`r`n" + '"' + $exe + '" %*'
Set-Content -Encoding ascii -Path $shim -Value $cmd
Ok "command created: $shim"

Write-Host ''
Ok "done! now run:  okami setup   (then  okami chat)"
