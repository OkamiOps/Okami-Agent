#!/usr/bin/env bash
# Okami Agent — instalador (Linux / macOS / WSL). TUDO numa pasta só: ~/.okami (ou $OKAMI_HOME).
#   curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
#
# Centraliza p/ não espalhar pelo SO:
#   ~/.okami/src    → o código (git clone)
#   ~/.okami/tools  → o venv isolado da ferramenta (UV_TOOL_DIR)
#   ~/.okami/bin    → o launcher `okami` (UV_TOOL_BIN_DIR)
#   ~/.okami/{skills,agents,sessions,.env,credentials,…} → dados/segredos (em runtime)
# O `uv` é o motor (instala o próprio Python + venv + deps). Você NÃO precisa de Python. Pré-req: git.
set -euo pipefail

OKAMI_DIR="${OKAMI_HOME:-$HOME/.okami}"
REPO_URL="${OKAMI_REPO:-https://github.com/OkamiOps/Okami-Agent.git}"
SRC="$OKAMI_DIR/src"
export OKAMI_HOME="$OKAMI_DIR"                  # a casa única (o runtime guarda dados aqui também)
export UV_TOOL_DIR="$OKAMI_DIR/tools"          # venvs das ferramentas → dentro de ~/.okami (não no padrão do uv)
export UV_TOOL_BIN_DIR="$OKAMI_DIR/bin"        # o launcher `okami` → dentro de ~/.okami

say()  { printf '\033[1;36m› %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

mkdir -p "$OKAMI_DIR"

# shell rc do shell atual (onde persistimos PATH/OKAMI_HOME).
shell_rc() {
  case "${SHELL:-}" in *zsh) echo "$HOME/.zshrc";; *bash) echo "$HOME/.bashrc";; *) echo "$HOME/.profile";; esac
}

# Garante $OKAMI_DIR/bin no PATH + persiste OKAMI_HOME se custom (sessão atual + rc, idempotente).
ensure_path() {
  local dir="$1" rc; rc="$(shell_rc)"
  case ":$PATH:" in *":$dir:"*) ;; *) export PATH="$dir:$PATH";; esac
  [ -n "$rc" ] || return 0
  if ! grep -qsF "$dir" "$rc" 2>/dev/null; then
    printf '\n# Okami — launcher em ~/.okami/bin\nexport PATH="%s:$PATH"\n' "$dir" >> "$rc"
    say "PATH atualizado em $rc (reabra o terminal se 'okami' não aparecer)"
  fi
  if [ "$OKAMI_DIR" != "$HOME/.okami" ] && ! grep -qsF "OKAMI_HOME=" "$rc" 2>/dev/null; then
    printf 'export OKAMI_HOME="%s"\n' "$OKAMI_DIR" >> "$rc"   # casa custom → runtime guarda dados lá
  fi
}

# 1) uv — instala se faltar (cuida de Python + venv + deps). uv é genérico → fica na pasta padrão dele.
if ! command -v uv >/dev/null 2>&1; then
  say "instalando o uv (gerencia Python + venv)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv não entrou no PATH — reabra o terminal e rode de novo."
ok "uv $(uv --version | awk '{print $2}')"

# 2) código → ~/.okami/src (ou usa o repo local, se rodando de dentro dele)
SDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SDIR" ] && [ -f "$SDIR/../pyproject.toml" ]; then
  SRC="$(cd "$SDIR/.." && pwd)"; say "usando o repo local: $SRC"
elif [ -d "$SRC/.git" ]; then
  say "atualizando $SRC"; git -C "$SRC" pull --ff-only || true
else
  command -v git >/dev/null 2>&1 || die "git é necessário para clonar."
  say "clonando em $SRC"; git clone --depth 1 "$REPO_URL" "$SRC"
fi

# 3) instala o `okami` como ferramenta isolada DENTRO de ~/.okami (UV_TOOL_DIR/BIN_DIR acima)
say "instalando o okami em $OKAMI_DIR…"
uv tool install --force "$SRC"
ensure_path "$OKAMI_DIR/bin"

# 4) migra um install antigo espalhado (~/.okami-agent) — só avisa, não apaga
if [ -d "$HOME/.okami-agent" ] && [ "$HOME/.okami-agent" != "$SRC" ]; then
  say "install antigo em ~/.okami-agent não é mais usado — pode remover: rm -rf ~/.okami-agent"
fi

ok "pronto! tudo em $OKAMI_DIR  (src/ · tools/ · bin/ · dados em runtime)"
printf '\n  Agora rode:  \033[1mokami setup\033[0m   (e depois  okami chat)\n'
printf '  Se "okami" não for encontrado, reabra o terminal.\n'
