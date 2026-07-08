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


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)


def git_pull(src: Path, *, allow_dirty: bool = False) -> tuple[bool, str]:
    """`git pull --ff-only` no checkout gerenciado — mesma política do install.sh (nunca reescreve
    histórico local silenciosamente). `allow_dirty=True` degrada pra "segue com o que já tem"
    em vez de abortar (espelha `OKAMI_INSTALL_ALLOW_DIRTY=1` do instalador). Retorna (ok, msg)."""
    if not shutil.which("git"):
        return False, "git não encontrado no PATH"
    result = _run(["git", "pull", "--ff-only"], cwd=src)
    if result.returncode == 0:
        return True, (result.stdout.strip() or "already up to date")
    if allow_dirty:
        return True, "git pull falhou — mantendo o checkout local como está (--allow-dirty)"
    return False, (result.stderr or result.stdout).strip() or "git pull falhou"


def uv_tool_install(src: Path) -> tuple[bool, str]:
    """`uv tool install --force <src>` — reinstala o `okami` isolado (mesmo passo 3 do install.sh)."""
    uv = shutil.which("uv")
    if not uv:
        return False, "uv não encontrado — instale: https://docs.astral.sh/uv/getting-started/installation/"
    result = _run([uv, "tool", "install", "--force", str(src)])
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout).strip() or "uv tool install falhou"


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

    console.print(f"› atualizando {src}…")
    ok, msg = git_pull(src, allow_dirty=allow_dirty)
    if not ok:
        console.print(
            f"[red]✗[/] git pull falhou: {msg}\n"
            "  Resolva (sem rede? working copy suja?), ou force com --allow-dirty."
        )
        raise typer.Exit(code=1)

    new = new_version_from_src(src) or "?"

    console.print("› reinstalando (uv tool install --force)…")
    ok, msg = uv_tool_install(src)
    if not ok:
        console.print(f"[red]✗[/] uv tool install falhou: {msg}")
        raise typer.Exit(code=1)

    if old == new:
        console.print(f"[green]✓[/] já estava na última versão: {old}")
    else:
        console.print(f"[green]✓[/] atualizado: {old} → {new}")
    console.print("  [dim]Abra um terminal novo (ou rode `hash -r`) se `okami --version` ainda mostrar a versão antiga.[/dim]")
