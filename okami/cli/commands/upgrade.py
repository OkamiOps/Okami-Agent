"""`okami upgrade` — atualiza a instalação global existente (~/.okami/src) pra última versão.

Fixa o gap #1 de "uso real": um install fica PARADO na versão de quando foi feito — o único
caminho de atualização era lembrar de rodar o instalador de novo (curl|bash / irm|iex), o que
a maioria não faz. `okami upgrade` vira comando de primeira classe: git pull no checkout
gerenciado ($OKAMI_HOME/src) + `uv tool install --force` (reinstala a ferramenta isolada) +
imprime versão_antiga → versão_nova. Mesma lógica que install.sh/install.ps1 já rodam nos
passos 2/3 quando re-executados (por isso os instaladores também são idempotentes-upgrade).

NÃO se aplica a:
  - instalação Docker: a imagem publicada não tem `.git` no contexto de build — `docker pull`
    (ou rebuild) é o caminho certo; ver `format_docker_upgrade_message()`.
  - checkout de DEV local (`uv sync` / `pip install -e .` num clone que você mesmo gerencia,
    fora de `~/.okami/src`): você já controla via `git pull` + `uv sync`; forçar aqui poderia
    mexer num checkout com trabalho em andamento que não tem nada a ver com `~/.okami`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from okami import __version__
from okami.cli._app import app, console
from okami.cli.commands.basics import _pyproject_version
from okami.home import okami_home
from okami.i18n import t as _tr

INSTALL_SH_URL = "https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh"


def in_docker() -> bool:
    """True se rodando dentro de um container Docker (imagem publicada — sem `.git`, sem upgrade
    in-place). Duas checagens (não dependem uma da outra): `/.dockerenv` (Docker Engine sempre
    cria) e o cgroup do PID 1 (cobre alguns runtimes que não criam o marker)."""
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def managed_src_dir() -> Path:
    """`~/.okami/src` (ou `$OKAMI_HOME/src`) — onde o instalador clona o código gerenciado.
    Fonte única: `okami.home.okami_home()`, a mesma casa usada pelo resto do runtime."""
    return okami_home() / "src"


def is_managed_checkout(src: Path) -> bool:
    """True só se `src` for um clone git de verdade (o layout que o instalador produz).
    Um `src/` sem `.git` (empacotado, ou apagado à mão) não é seguro pra `git pull`."""
    return (src / ".git").exists()


def detect_install_kind(src: Path | None = None) -> str:
    """'docker' | 'managed' | 'dev-local' | 'missing' — decide o que `okami upgrade` deve fazer.

    'dev-local': o processo rodando não veio do checkout gerenciado — você tem seu próprio
    clone (dev). Nunca mexemos nele por engano."""
    if in_docker():
        return "docker"
    if src is None:
        src = managed_src_dir()
    if not src.exists():
        return "missing"
    if not is_managed_checkout(src):
        return "dev-local"
    return "managed"


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, env=env)


def _head_sha(src: Path) -> str:
    """SHA curto do HEAD do checkout — a versão em pyproject nem sempre bumpa a cada commit, então
    comparar SHA (não só a string de versão) é o que revela se o `git pull` de fato trouxe código novo."""
    if not shutil.which("git"):
        return ""
    r = _run(["git", "rev-parse", "--short", "HEAD"], cwd=src)
    return r.stdout.strip() if r.returncode == 0 else ""


def _default_branch(src: Path) -> str:
    """Branch que o origin considera HEAD (normalmente 'main'). Fallback: 'main'."""
    r = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=src)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[-1]      # 'origin/main' → 'main'
    return "main"


def git_pull(src: Path, *, allow_dirty: bool = False) -> tuple[bool, str]:
    """Traz a ÚLTIMA versão do GitHub de forma robusta (padrão Hermes) — `git fetch origin` + reconcilia
    o checkout gerenciado com `origin/<branch>`, em vez de `git pull --ff-only` (que vira NO-OP silencioso
    ou aborta quando o checkout divergiu/tem mudança local — foi o que fazia o upgrade "não pegar").

    Mudanças locais no src gerenciado NÃO são para existir (é código, não dados do usuário — esses moram
    fora, em ~/.okami). Fazemos `stash -u` de segurança antes do reset (nada é perdido — fica no stash),
    depois `reset --hard origin/<branch>`. Retorna (ok, msg)."""
    if not shutil.which("git"):
        return False, "git não encontrado no PATH"
    fetch = _run(["git", "fetch", "origin", "--prune"], cwd=src)
    if fetch.returncode != 0:
        if allow_dirty:
            return True, "git fetch falhou — mantendo o checkout local (--allow-dirty / sem rede?)"
        return False, (fetch.stderr or fetch.stdout).strip() or "git fetch falhou (sem rede?)"
    branch = _default_branch(src)
    # mudança local no src (não deveria haver) → stash de segurança, nunca reset --hard cego perdendo tudo
    dirty = _run(["git", "status", "--porcelain"], cwd=src).stdout.strip()
    if dirty:
        _run(["git", "stash", "push", "-u", "-m", "okami-upgrade-autostash"], cwd=src)
    reset = _run(["git", "reset", "--hard", f"origin/{branch}"], cwd=src)
    if reset.returncode != 0:
        return False, (reset.stderr or reset.stdout).strip() or f"git reset p/ origin/{branch} falhou"
    return True, (reset.stdout.strip() or f"reconciliado com origin/{branch}")


def _tool_env() -> dict:
    """Env do `uv tool install` apontando p/ o MESMO local do okami em execução — senão o upgrade
    reinstala num lugar (default do uv, ~/.local) diferente do binário que a pessoa roda (ex.: ~/.okami/bin
    do install.sh) e a versão "não muda". Se o venv atual está sob $OKAMI_HOME (install gerenciado),
    força UV_TOOL_DIR/UV_TOOL_BIN_DIR = ~/.okami/{tools,bin} (idêntico ao install.sh); senão, default do uv."""
    env = dict(os.environ)
    home = Path(os.environ.get("OKAMI_HOME") or (Path.home() / ".okami")).resolve()
    venv = Path(sys.prefix).resolve()
    try:
        under_home = venv == home or home in venv.parents
    except OSError:
        under_home = False
    if under_home:
        env["UV_TOOL_DIR"] = str(home / "tools")
        env["UV_TOOL_BIN_DIR"] = str(home / "bin")
    return env


def uv_tool_install(src: Path) -> tuple[bool, str]:
    """`uv tool install --reinstall --force <src>` — reinstala o `okami` isolado NO MESMO local do
    binário em execução (ver _tool_env).

    `--reinstall` é OBRIGATÓRIO, não só `--force`: `--force` sobrescreve o entry-point mas REUSA o build
    em cache do pacote — então um `git pull` que muda só o CÓDIGO (sem bump de versão) NÃO chegava ao venv
    instalado, e o `okami upgrade` "não pegava" (o src atualizava, o venv rodado ficava velho). `--reinstall`
    reconstrói o pacote a partir do src atual, que é o que o comando promete."""
    uv = shutil.which("uv")
    if not uv:
        return False, "uv não encontrado — instale: https://docs.astral.sh/uv/getting-started/installation/"
    result = _run([uv, "tool", "install", "--reinstall", "--force", str(src)], env=_tool_env())
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout).strip() or "uv tool install falhou"


def installed_bin_path(env: dict | None = None) -> Path:
    """Onde o `okami` recém-(re)instalado REALMENTE mora — mesmo UV_TOOL_BIN_DIR que `_tool_env()`
    força pro `uv tool install` (ver ali). Sem isso o shadow-check compararia contra o default do
    uv mesmo quando o install é gerenciado (~/.okami/bin), gerando falso positivo/negativo."""
    env = env if env is not None else _tool_env()
    bin_dir = env.get("UV_TOOL_BIN_DIR")
    if bin_dir:
        return Path(bin_dir) / "okami"
    return Path.home() / ".local" / "bin" / "okami"


def shadow_warning(installed: Path) -> str | None:
    """Se o `okami` que o PATH do usuário resolve HOJE não é o binário que acabamos de instalar,
    ele vai continuar sendo o que o shell chama — a pessoa roda `okami upgrade`, some sucesso, mas
    `okami --version` teima na versão velha. Mesma checagem que o install.sh faz no passo 5b.
    Retorna None quando está tudo certo (PATH resolve pro binário novo, ou nada no PATH ainda)."""
    on_path = shutil.which("okami")
    if not on_path:
        return None
    on_path_p = Path(on_path)
    try:
        same = on_path_p.resolve() == installed.resolve()
    except OSError:
        same = on_path_p == installed
    if same:
        return None
    return (
        f"[yellow]⚠[/] o `okami` no seu PATH ainda aponta pra outro binário: {on_path}\n"
        f"  O upgrade foi instalado em {installed} — é por isso que `okami --version` pode "
        "continuar mostrando a versão velha.\n"
        f"  Resolva removendo o antigo (ex.: [bold]rm -f {on_path}[/bold] ou `pipx uninstall "
        "okami-agent`) ou ajustando a ordem do PATH, e reabra o terminal."
    )


def new_version_from_src(src: Path) -> str | None:
    """Lê a versão do `pyproject.toml` recém-puxado — reflete o código PÓS `git pull` sem precisar
    reimportar `okami` (o processo atual já carregou o módulo antigo em memória; reimportar não
    pegaria o arquivo reinstalado de qualquer forma dentro do mesmo processo)."""
    pp = src / "pyproject.toml"
    if not pp.exists():
        return None
    return _pyproject_version(pp.read_text(encoding="utf-8"))


def format_docker_upgrade_message() -> str:
    return (
        "[yellow]⚠[/] Você está rodando a imagem Docker do Okami — ela não tem `.git` (o build "
        "exclui), então `okami upgrade` não se aplica aqui.\n"
        "  Atualize puxando/reconstruindo a imagem:\n"
        "    docker pull okami-agent   [dim](se publicada num registry)[/dim]\n"
        "    # ou, a partir do repo:\n"
        "    git pull && make docker-build\n"
        "  Os dados (`~/.okami`) ficam no volume montado — sobrevivem à troca de imagem."
    )


@app.command(help=_tr("cli.upgrade", _default="Update the global install to the latest version (git pull + reinstall)."))
def upgrade(
    yes: bool = typer.Option(False, "--yes", "-y", help=_tr("cli.upgrade.yes", _default="Don't prompt for confirmation.")),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help=_tr("cli.upgrade.allow_dirty", _default="If `git pull` fails, keep the existing local checkout instead of aborting.")),
    check: bool = typer.Option(False, "--check", help=_tr("cli.upgrade.check", _default="Only report the current version, don't upgrade.")),
) -> None:
    """Atualiza a instalação global em uso: `git pull` no checkout gerenciado + `uv tool install
    --force` (reinstala) + imprime versão_antiga → versão_nova. Ver docstring do módulo pros
    casos que NÃO se aplicam (docker / checkout de dev)."""
    old = __version__
    src = managed_src_dir()
    kind = detect_install_kind(src)

    if check:
        console.print(f"okami {old}  [dim]({kind}, {src if kind != 'docker' else 'container'})[/dim]")
        return

    if kind == "docker":
        console.print(format_docker_upgrade_message())
        raise typer.Exit(code=1)
    if kind == "missing":
        console.print(
            f"[red]✗[/] {src} não existe — isto não parece uma instalação gerenciada pelo instalador.\n"
            f"  Rode o instalador:\n    curl -fsSL {INSTALL_SH_URL} | bash"
        )
        raise typer.Exit(code=1)
    if kind == "dev-local":
        console.print(
            f"[yellow]⚠[/] Checkout de DEV (não é o gerenciado em {src}) — atualize manualmente:\n"
            "    git pull && uv sync   [dim](ou: uv tool install -e . --force)[/dim]"
        )
        raise typer.Exit(code=1)

    if not yes and sys.stdin.isatty() and not typer.confirm(
        f"Atualizar {src} (versão atual: {old}) e reinstalar?", default=True
    ):
        raise typer.Exit(code=0)

    sha_before = _head_sha(src)                       # p/ saber se o pull trouxe COMMIT novo (versão pode não bumpar)
    console.print(f"› atualizando {src}…")
    ok, msg = git_pull(src, allow_dirty=allow_dirty)
    if not ok:
        console.print(
            f"[red]✗[/] git pull falhou: {msg}\n"
            "  Resolva (sem rede? working copy suja?), ou force com --allow-dirty."
        )
        raise typer.Exit(code=1)

    new = new_version_from_src(src) or "?"
    sha_after = _head_sha(src)

    console.print("› reinstalando (uv tool install --force)…")
    ok, msg = uv_tool_install(src)
    if not ok:
        console.print(f"[red]✗[/] uv tool install falhou: {msg}")
        raise typer.Exit(code=1)

    # Compara por SHA de commit, não só string de versão — muitos commits saem sem bumpar a versão em
    # pyproject, e antes o upgrade dizia "já estava na última versão" mesmo tendo puxado código novo.
    changed = bool(sha_before and sha_after and sha_before != sha_after)
    if changed:
        vtxt = f"{old} → {new}" if old != new else new
        console.print(f"[green]✓[/] atualizado: {vtxt}  [dim]({sha_before} → {sha_after})[/dim]")
    elif old != new:
        console.print(f"[green]✓[/] atualizado: {old} → {new}")
    else:
        console.print(f"[green]✓[/] já estava na última versão: {old} [dim]({sha_after})[/dim]")
    console.print("  [dim]Abra um terminal novo (ou rode `hash -r`) se `okami --version` ainda mostrar a versão antiga.[/dim]")

    warning = shadow_warning(installed_bin_path())
    if warning:
        console.print(warning)
