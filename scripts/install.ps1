# Okami Agent - installer for Windows (PowerShell). ASCII-only (PS 5.1 le .ps1 sem BOM como ANSI).
#   irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex
#
# O `uv` e o motor: instala o proprio Python, cria o venv isolado e as deps numa tacada.
# Voce NAO precisa de Python instalado. Sem dor de long-path (o uv usa um diretorio curto = resolve
# o problema do litellm no OneDrive). Unico pre-requisito: git.
[CmdletBinding()]
param(
  [string]$RepoUrl = $(if ($env:OKAMI_REPO) { $env:OKAMI_REPO } else { 'https://github.com/OkamiOps/Okami-Agent.git' }),
  [string]$Dest    = $(if ($env:OKAMI_HOME) { $env:OKAMI_HOME } else { "$HOME\.okami-agent" })
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "[ok] $m" -ForegroundColor Green }
function Die($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

# 1) uv - instala se faltar (cuida de Python + venv + deps)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "instalando o uv (gerencia Python + venv)..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv nao entrou no PATH - reabra o PowerShell e rode de novo." }
Ok "uv $((uv --version) -replace 'uv ','')"

# 2) codigo - repo local (se rodando de dentro) OU clona
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($scriptDir -and (Test-Path (Join-Path $scriptDir '..\pyproject.toml'))) {
  $Dest = (Resolve-Path (Join-Path $scriptDir '..')).Path; Say "usando o repo local: $Dest"
} elseif (Test-Path (Join-Path $Dest '.git')) {
  Say "atualizando $Dest"; git -C $Dest pull --ff-only 2>$null
} else {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git e necessario para clonar." }
  Say "clonando em $Dest"; git clone --depth 1 $RepoUrl $Dest
}

# 3) instala o okami como ferramenta GLOBAL isolada (uv baixa um Python compativel se faltar)
Say "instalando o okami..."
uv tool install --force $Dest
uv tool update-shell 2>$null

Ok "pronto!"
Write-Host ''
Write-Host "Agora rode: okami setup   (e depois  okami chat)" -ForegroundColor White
Write-Host 'Se "okami" nao for encontrado, reabra o PowerShell.'
