#!/usr/bin/env bash
# Okami Agent — instalador para Linux / macOS / WSL.
#   curl -fsSL https://raw.githubusercontent.com/<owner>/okami-agent/main/scripts/install.sh | bash
# ou, dentro do repo já clonado:  ./scripts/install.sh
#
# Detecta o que falta (Python 3.11+, venv) e prepara um comando `okami` global.
# Inspirado no install.sh do Hermes (deps automáticas + comando global).
set -euo pipefail

REPO_URL="${OKAMI_REPO:-https://github.com/okami-agent/okami-agent.git}"
DEST="${OKAMI_HOME:-$HOME/.okami-agent}"
BIN_DIR="${OKAMI_BIN:-$HOME/.local/bin}"
PYTHON="${OKAMI_PYTHON:-python3}"

say()  { printf '\033[1;36m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 1) Python 3.11+ -----------------------------------------------------------
have_py() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys;exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; }
if ! have_py "$PYTHON"; then
  for c in python3.13 python3.12 python3.11 python3; do have_py "$c" && PYTHON="$c" && break; done
fi
have_py "$PYTHON" || die "preciso de Python 3.11+ (instale via apt/brew/pyenv e rode de novo)."
ok "Python: $($PYTHON --version)"

# 2) Código (repo local OU clona) ------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../pyproject.toml" ]; then
  DEST="$(cd "$SCRIPT_DIR/.." && pwd)"; say "usando o repo local em $DEST"
elif [ -d "$DEST/.git" ]; then
  say "atualizando $DEST"; git -C "$DEST" pull --ff-only || true
else
  command -v git >/dev/null 2>&1 || die "git é necessário para clonar (instale o git)."
  say "clonando em $DEST"; git clone --depth 1 "$REPO_URL" "$DEST"
fi

# 3) venv + instalação ------------------------------------------------------
say "criando venv e instalando…"
"$PYTHON" -m venv "$DEST/.venv"
# shellcheck disable=SC1091
. "$DEST/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -e "$DEST"
ok "Okami instalado ($(okami version 2>/dev/null || echo '?'))"

# 4) comando global `okami` -------------------------------------------------
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/okami" <<EOF
#!/usr/bin/env bash
exec "$DEST/.venv/bin/okami" "\$@"
EOF
chmod +x "$BIN_DIR/okami"
ok "comando criado: $BIN_DIR/okami"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "adicione ao PATH:  export PATH=\"$BIN_DIR:\$PATH\"  (no seu ~/.bashrc/~/.zshrc)";;
esac

printf '\n'; ok "pronto! agora rode:  \033[1mokami setup\033[0m   (e depois  okami chat)"
