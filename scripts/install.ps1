# Okami Agent - installer for Windows (PowerShell). ASCII-only (PS 5.1 le .ps1 sem BOM como ANSI).
#   irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex
#
# Centraliza TUDO numa pasta so: %USERPROFILE%\.okami (ou $env:OKAMI_HOME). Nada espalhado pelo SO:
#   .okami\src   -> o codigo (git clone)
#   .okami\tools -> o venv isolado da ferramenta (UV_TOOL_DIR)
#   .okami\bin   -> o launcher 'okami' (UV_TOOL_BIN_DIR)
#   .okami\{skills,agents,sessions,.env,credentials,...} -> dados/segredos (em runtime)
# O `uv` e o motor (instala Python + venv + deps). Voce NAO precisa de Python. Pre-req: git.
[CmdletBinding()]
param(
  [string]$RepoUrl = $(if ($env:OKAMI_REPO) { $env:OKAMI_REPO } else { 'https://github.com/OkamiOps/Okami-Agent.git' })
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "[ok] $m" -ForegroundColor Green }
function Die($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

$OkamiDir = $(if ($env:OKAMI_HOME) { $env:OKAMI_HOME } else { "$env:USERPROFILE\.okami" })
$Src      = Join-Path $OkamiDir 'src'
New-Item -ItemType Directory -Force -Path $OkamiDir | Out-Null
$env:OKAMI_HOME     = $OkamiDir                 # a casa unica (runtime guarda dados aqui)
$env:UV_TOOL_DIR    = Join-Path $OkamiDir 'tools'   # venvs das ferramentas -> dentro de .okami
$env:UV_TOOL_BIN_DIR = Join-Path $OkamiDir 'bin'    # launcher 'okami' -> dentro de .okami

# 1) uv - instala se faltar. uv e generico -> fica na pasta padrao dele.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "instalando o uv (gerencia Python + venv)..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv nao entrou no PATH - reabra o PowerShell e rode de novo." }
Ok "uv $((uv --version) -replace 'uv ','')"

# 2) codigo -> .okami\src (ou usa o repo local, se rodando de dentro)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($scriptDir -and (Test-Path (Join-Path $scriptDir '..\pyproject.toml'))) {
  $Src = (Resolve-Path (Join-Path $scriptDir '..')).Path; Say "usando o repo local: $Src"
} elseif (Test-Path (Join-Path $Src '.git')) {
  Say "atualizando $Src"
  git -C $Src pull --ff-only
  if ($LASTEXITCODE -ne 0) {
    if ($env:OKAMI_INSTALL_ALLOW_DIRTY -eq '1') {
      Say "git pull falhou - OKAMI_INSTALL_ALLOW_DIRTY=1 -> instalando a versao LOCAL existente (pode estar velha)."
    } else {
      Die "git pull falhou (sem rede? working copy suja?). Resolva, ou force com OKAMI_INSTALL_ALLOW_DIRTY=1."
    }
  }
} else {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git e necessario para clonar." }
  Say "clonando em $Src"; git clone --depth 1 $RepoUrl $Src
}

# 3) instala o okami DENTRO de .okami (UV_TOOL_DIR/BIN_DIR acima)
Say "instalando o okami em $OkamiDir..."
uv tool install --force $Src

# 4) PATH do usuario: garante .okami\bin (idempotente) + OKAMI_HOME se custom
$binDir = Join-Path $OkamiDir 'bin'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$binDir*") {
  [Environment]::SetEnvironmentVariable('Path', "$binDir;$userPath", 'User')
  Say "PATH do usuario atualizado com $binDir (reabra o PowerShell)"
}
$env:Path = "$binDir;$env:Path"
if ($OkamiDir -ne "$env:USERPROFILE\.okami") {
  [Environment]::SetEnvironmentVariable('OKAMI_HOME', $OkamiDir, 'User')   # casa custom -> runtime guarda dados la
}

# 5) avisa de install antigo espalhado
$old = "$env:USERPROFILE\.okami-agent"
if ((Test-Path $old) -and ($old -ne $Src)) { Say "install antigo em .okami-agent nao e mais usado - pode remover: Remove-Item -Recurse -Force $old" }

Ok "pronto! tudo em $OkamiDir  (src\ tools\ bin\ + dados em runtime)"
Write-Host ''
Write-Host "Agora rode: okami setup   (e depois  okami chat)" -ForegroundColor White
Write-Host 'Se "okami" nao for encontrado, reabra o PowerShell.'
