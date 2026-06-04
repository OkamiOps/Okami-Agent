"""CLI do Okami (Fase 0).

Comandos:
  okami run "<prompt>"     -> uma ida-e-volta ao provider (default ou --provider)
  okami providers          -> lista providers e se estão prontos
  okami doctor             -> diagnostica config, chaves e conectividade
"""

from __future__ import annotations

import json
import platform
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from pathlib import Path

from okami import __version__
from okami.llm import providers as prov
from okami.config import OkamiConfig, load_config
from okami.core import Budget, Harness, Task, TaskState

app = typer.Typer(add_completion=False, help="Okami Agent — CLI")

# UTF-8 consistente em qualquer SO (resolve acentos/§ no console Windows; no-op em Linux/macOS).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

console = Console()


def _load() -> OkamiConfig:
    try:
        return load_config()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Falha ao carregar config:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Prompt para o agente."),
    provider: str = typer.Option(None, "--provider", "-p", help="Nome do provider (default: do okami.yaml)."),
    model: str = typer.Option(None, "--model", "-m", help="Sobrescreve o model do provider."),
    system: str = typer.Option(None, "--system", "-s", help="System prompt opcional."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Desliga streaming."),
) -> None:
    """Faz uma ida-e-volta ao provider (Fase 0)."""
    cfg = _load()
    try:
        pc = cfg.provider(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[dim]provider=[/dim][bold]{pc.name}[/bold] "
        f"[dim]model=[/dim]{model or pc.model} [dim]tier=[/dim]{pc.tier}"
    )
    if not pc.ready:
        console.print(
            f"[yellow]Aviso:[/yellow] provider '{pc.name}' sem chave "
            f"(defina {pc.api_key_env}). Tentando mesmo assim..."
        )

    try:
        if no_stream:
            out = prov.complete(cfg, prompt, provider=provider, system=system, model=model)
            console.print(out)
        else:
            for piece in prov.stream_complete(
                cfg, prompt, provider=provider, system=system, model=model
            ):
                sys.stdout.write(piece)
                sys.stdout.flush()
            sys.stdout.write("\n")
    except Exception as e:  # noqa: BLE001
        console.print(f"\n[red]Erro na chamada:[/red] {e}")
        raise typer.Exit(1)


@app.command("providers")
def list_providers() -> None:
    """Lista os providers configurados e se estão prontos."""
    cfg = _load()
    table = Table(title="Okami providers")
    table.add_column("nome", style="bold")
    table.add_column("tier")
    table.add_column("model")
    table.add_column("api_base")
    table.add_column("pronto?")
    for name, pc in cfg.providers.items():
        flag = "[green]sim[/green]" if pc.ready else "[yellow]falta chave[/yellow]"
        default_mark = " [cyan](default)[/cyan]" if name == cfg.default_provider else ""
        table.add_row(name + default_mark, pc.tier, pc.model, pc.api_base or "-", flag)
    console.print(table)


def _ping_models(api_base: str, timeout: float = 6.0) -> tuple[bool, str]:
    url = api_base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", [])]
        return True, f"{len(ids)} modelos" + (f" (ex.: {ids[0]})" if ids else "")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, str(e)


@app.command()
def doctor() -> None:
    """Diagnostica config, chaves e conectividade dos providers."""
    console.print(f"[bold]Okami[/bold] v{__version__} — doctor")
    console.print(
        f"[dim]{platform.system()} {platform.release()} · Python {platform.python_version()}[/dim]"
    )
    cfg = _load()
    console.print(f"default_provider: [bold]{cfg.default_provider}[/bold]\n")

    for name, pc in cfg.providers.items():
        console.print(f"[bold]{name}[/bold] ({pc.tier})")
        console.print(f"  model: {pc.model}")
        if pc.transport == "claude_cli":
            s = "[green]CLI 'claude' OK[/green]" if pc.ready else "[yellow]instale/logue o CLI 'claude'[/yellow]"
            console.print(f"  transport: claude_cli — {s}")
        elif pc.transport == "codex_oauth":
            s = "[green]~/.codex/auth.json OK[/green]" if pc.ready else f"[yellow]rode: okami login {name}[/yellow]"
            console.print(f"  transport: codex_oauth — {s}")
        elif pc.transport == "minimax_oauth":
            s = "[green]token OAuth OK[/green]" if pc.ready else f"[yellow]rode: okami login {name}[/yellow]"
            console.print(f"  transport: minimax_oauth — {s}")
        elif pc.api_key_env:
            mark = "[green]ok[/green]" if pc.resolved_key() else f"[yellow]definir {pc.api_key_env}[/yellow]"
            console.print(f"  chave: {mark}")
        elif pc.api_key:
            console.print("  chave: [green]literal/dummy[/green]")
        else:
            console.print("  chave: [dim]nenhuma[/dim]")
        if pc.api_base:
            ok, msg = _ping_models(pc.api_base)
            color = "green" if ok else "red"
            console.print(f"  endpoint {pc.api_base}: [{color}]{msg}[/{color}]")
        if pc.notes:
            console.print(f"  [dim]nota: {pc.notes}[/dim]")
        console.print()

    # --- memória (útil p/ setup distribuído via Tailscale) ---
    mem = cfg.memory or {}
    console.print(f"[bold]memória[/bold]: backend={mem.get('backend', 'sqlite-fts5')}")
    emb = mem.get("embedder") or {}
    if emb.get("enabled", True) and emb.get("model"):
        from okami.memory import OpenAICompatEmbedder
        e = OpenAICompatEmbedder(emb.get("api_base", "http://localhost:1234/v1"), emb["model"])
        ok = e.available()
        s = "[green]ok[/green]" if ok else "[yellow]offline → degrada p/ BM25[/yellow]"
        console.print(f"  embedder {emb.get('api_base')}: {s}")
    hc = mem.get("honcho")
    if hc:
        console.print(f"  honcho: {hc.get('base_url', '(base_url não definido)')}")
    fl = mem.get("files", {})
    console.print("  .md sempre injetados: identidade (SOUL/VOICE/PERSONA) + core (AGENTS/USER/MEMORY)")
    console.print(f"  limites (chars): soul={fl.get('soul', 6000)} voice={fl.get('voice', 6000)} "
                  f"persona={fl.get('persona', 6000)} agents={fl.get('agents', 4000)} "
                  f"user={fl.get('user', 4000)} memory={fl.get('memory', 4000)}")


def _persist_always_allow(category: str) -> None:
    """Adiciona uma categoria ao approvals.always_allow em okami.local.yaml (cross-sessão)."""
    import yaml as _yaml

    p = Path("okami.local.yaml")
    data = {}
    if p.exists():
        data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    appr = data.setdefault("approvals", {})
    allow = appr.setdefault("always_allow", [])
    if category not in allow:
        allow.append(category)
    p.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_approver(cfg, yolo: bool = False, mode: str | None = None):
    """Aprovador interativo da CLI (go/no-go com 4 opções + persistência)."""
    from okami.core.approval import Approver

    appr = cfg.approvals or {}
    mode_eff = "yolo" if yolo else (mode or appr.get("mode", "manual"))

    def _prompt(req: dict) -> str:
        console.print(f"  [bold yellow]⚠ GO/NO-GO[/bold yellow] {req['reason']} [dim](risco={req['risk']})[/dim]")
        console.print("    [1] allow once   [2] allow session   [3] always allow   [4] deny")
        try:
            sel = typer.prompt("    escolha", default="4")
        except Exception:  # noqa: BLE001 — não-interativo → fail-closed
            return "deny"
        return {"1": "once", "2": "session", "3": "always", "4": "deny"}.get(str(sel).strip(), "deny")

    def _persist(cat: str) -> None:
        _persist_always_allow(cat)
        console.print(f"  [dim]always-allow '{cat}' salvo em okami.local.yaml[/dim]")

    return Approver(mode=mode_eff, persistent_allow=set(appr.get("always_allow", [])),
                    prompt=_prompt, on_persist=_persist)


def _parse_exit(spec: str) -> dict:
    """'file_exists:foo.txt' | 'shell_ok:pytest -q' | 'file_contains:foo.txt:hello'."""
    kind, _, rest = spec.partition(":")
    if kind == "file_exists":
        return {"type": "file_exists", "path": rest}
    if kind == "shell_ok":
        return {"type": "shell_ok", "cmd": rest}
    if kind == "file_contains":
        path, _, text = rest.partition(":")
        return {"type": "file_contains", "path": path, "text": text}
    raise typer.BadParameter(f"critério de saída desconhecido: {spec}")


_STATE_COLOR = {
    TaskState.COMPLETE: "green", TaskState.BLOCKED: "yellow",
    TaskState.NEEDS_INPUT: "cyan", TaskState.FAILED: "red",
}


@app.command()
def task(
    goal: str = typer.Argument(..., help="Objetivo da tarefa."),
    provider: str = typer.Option(None, "--provider", "-p"),
    model: str = typer.Option(None, "--model", "-m"),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w", help="Diretório de trabalho."),
    exit_: list[str] = typer.Option(None, "--exit", "-e", help="Critério de saída (repetível)."),
    max_steps: int = typer.Option(24, "--max-steps"),
    escalate_to: str = typer.Option(None, "--escalate", help="Provider forte p/ cascata se travar (§3.5)."),
    yes: bool = typer.Option(False, "--yes", "-y", "--yolo", help="YOLO: auto-aprova tudo na sessão."),
    mode: str = typer.Option(None, "--mode", help="Aprovação: manual | smart | off."),
    agent: str = typer.Option(None, "--agent", "-a", help="Rodar como um agente (agents/<id>)."),
) -> None:
    """Roda o harness até COMPLETE/BLOCKED/NEEDS_INPUT/FAILED."""
    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        graw, _ = load_raw()
        specs = load_agents()
        if agent not in specs:
            console.print(f"[red]agente '{agent}' não existe. Crie: okami agent new {agent}[/red]")
            raise typer.Exit(1)
        cfg = effective_config(graw, specs[agent])
        ws = specs[agent].dir
        console.print(f"[dim]agente:[/dim] [bold]{agent}[/bold] [dim](workspace {ws})[/dim]")
    else:
        cfg = _load()
        ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    criteria = []
    for s in (exit_ or []):
        if s == "ui_gate":
            criteria.append({"type": "ui_gate", "contract": cfg.contracts.get("ui", {}), "path": "."})
        else:
            criteria.append(_parse_exit(s))

    def on_event(e: dict) -> None:
        k = e["kind"]
        if k == "start":
            console.print(f"[bold]▶ tarefa:[/bold] {e['goal']}\n[dim]workspace={ws}[/dim]")
        elif k == "step":
            mark = "[green]ok[/green]" if e["ok"] else "[red]erro[/red]"
            console.print(f"  [dim]{e['n']:>2}[/dim] {e['tool']} → {mark}")
        elif k == "violation":
            console.print(f"  [yellow]⟲ rejeitado (sem ação) #{e['n']}[/yellow]")
        elif k == "loop":
            console.print(f"  [yellow]⟲ loop detectado[/yellow] (x{e['repeats']})")
        elif k == "escalate":
            console.print(f"  [magenta]⬆ escalando p/ '{escalate_to}'[/magenta] [dim]({e['why']})[/dim]")
        elif k == "compact":
            console.print(f"  [blue]⊟ auto-compaction[/blue] [dim]({e['promoted']} → memória)[/dim]")
        elif k == "complete_rejected":
            console.print(f"  [yellow]✗ task_complete rejeitado:[/yellow] {', '.join(e['missing'])}")

    approver = _build_approver(cfg, yolo=yes, mode=mode)
    if approver.mode in ("yolo", "off"):
        console.print(f"[dim]aprovação: {approver.mode} (sem prompts)[/dim]")

    from okami.runner import run_task
    try:
        result = run_task(cfg, ws, goal, exit_criteria=criteria, provider=provider, model=model,
                          approve=approver, on_event=on_event, max_steps=max_steps,
                          escalate_to=escalate_to, emit=lambda m: console.print(f"[dim]{m}[/dim]"))
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Erro no harness:[/red] {e}")
        raise typer.Exit(1)

    color = _STATE_COLOR.get(result.state, "white")
    console.print(f"\n[bold {color}]{result.state.value}[/bold {color}] "
                  f"[dim]({len(result.steps)} passos)[/dim]")
    if result.result:
        console.print(result.result)
    if result.reason:
        console.print(f"[dim]{result.reason}[/dim]")
    if result.state != TaskState.COMPLETE:
        raise typer.Exit(2)


@app.command()
def login(
    provider: str = typer.Argument(..., help="Provider para autenticar (ex.: codex, minimax)."),
) -> None:
    """Autentica um provider de assinatura (device flow / CLI oficial)."""
    from okami.llm import oauth

    cfg = _load()
    try:
        pc = cfg.provider(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if pc.transport == "codex_oauth":  # device flow NATIVO da OpenAI (sem codex CLI)
        try:
            oauth.codex_device_login(lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green]")
        return

    if pc.login_cmd:  # delega ao CLI oficial (fallback opcional)
        console.print(f"[dim]delegando para:[/dim] {' '.join(pc.login_cmd)}")
        try:
            rc = oauth.cli_delegate_login(pc.login_cmd)
        except FileNotFoundError:
            console.print(f"[red]CLI '{pc.login_cmd[0]}' não encontrado.[/red] Instale-o e tente de novo.")
            raise typer.Exit(1)
        raise typer.Exit(rc)

    if pc.oauth:  # device flow nativo genérico (MiniMax)
        try:
            oauth.device_login(provider, pc.oauth, lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green]")
        return

    console.print(f"[yellow]'{provider}' não tem fluxo de login.[/yellow] Use .env/api_key.")


@app.command()
def gate(
    path: str = typer.Argument(".", help="Diretório a verificar."),
    contract: str = typer.Option("ui", "--contract", "-c", help="Nome do contrato em okami.yaml."),
) -> None:
    """Roda o verification gate de design (§4.3) sobre um diretório."""
    from okami.contracts import check_ui

    cfg = _load()
    spec = cfg.contracts.get(contract)
    if not spec:
        console.print(f"[red]Contrato '{contract}' não existe em okami.yaml[/red]")
        raise typer.Exit(1)
    viols = check_ui(Path(path), spec)
    if not viols:
        console.print(f"[green]✓ gate '{contract}' passou[/green] em {path}")
        return
    console.print(f"[red]✗ {len(viols)} violações[/red] (contrato '{contract}'):")
    for v in viols:
        console.print(f"  {v}")
    raise typer.Exit(1)


@app.command()
def skills() -> None:
    """Lista as skills disponíveis (skills/*/SKILL.md)."""
    from okami import skills as skillmod

    sks = skillmod.load_skills(Path("skills"))
    if not sks:
        console.print("[dim]nenhuma skill em ./skills[/dim]")
        return
    table = Table(title="Okami skills")
    table.add_column("nome", style="bold")
    table.add_column("triggers")
    table.add_column("descrição")
    for s in sks:
        table.add_row(s.name, ", ".join(s.triggers[:5]), s.description[:60])
    console.print(table)


def _print_risk_report(report) -> None:
    from okami.skills.skill_security import SEV_NAME
    if not report.findings:
        console.print("[green]✓ scan limpo — nenhum sinal de risco[/green]")
        return
    colors = {"CRITICAL": "red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}
    console.print(f"[bold]Risco máximo:[/bold] {SEV_NAME[report.max_severity]}")
    for f in report.sorted():
        sev = SEV_NAME[f.severity]
        c = colors.get(sev, "white")
        console.print(f"  [{c}]{sev}[/{c}] {f.file}:{f.line} [bold]{f.rule}[/bold] — {f.why}")
        if f.snippet:
            console.print(f"      [dim]{f.snippet}[/dim]")


def _fetch_skill_source(source: str, dest: Path) -> None:
    import shutil
    import subprocess

    dest.mkdir(parents=True, exist_ok=True)
    local = Path(source)
    if local.exists():  # caminho local
        shutil.copytree(local, dest / local.name, dirs_exist_ok=True)
        return
    if source.startswith("clawhub:"):  # ClawHub
        subprocess.call(["npx", "clawhub", "install", source.split(":", 1)[1]], cwd=str(dest))
        return
    url = f"https://github.com/{source}.git" if re.match(r"^[\w.-]+/[\w.-]+$", source) else source
    subprocess.call(["git", "clone", "--depth", "1", url], cwd=str(dest))


@app.command()
def scan(path: str = typer.Argument(..., help="Diretório/arquivo de skill a verificar.")) -> None:
    """Verifica risco de uma skill (prompt injection, malware, exfiltração de segredos)."""
    from okami.skills.skill_security import scan_path

    report = scan_path(Path(path))
    _print_risk_report(report)
    raise typer.Exit(2 if report.blocked else 0)


@app.command()
def learn(
    source: str = typer.Argument(..., help="owner/repo, URL, caminho local, ou clawhub:<slug>."),
    force: bool = typer.Option(False, "--force", help="Instalar mesmo se o scan BLOQUEAR (perigoso)."),
) -> None:
    """Baixa uma skill, VALIDA (quarentena + scan) e só então instala em ./skills (skill.sh/ClawHub)."""
    import shutil

    from okami import skills as skillmod
    from okami.skills.skill_security import scan_path

    quarantine = Path(".okami") / "quarantine"
    shutil.rmtree(quarantine, ignore_errors=True)
    console.print(f"[dim]baixando para quarentena:[/dim] {quarantine}")
    try:
        _fetch_skill_source(source, quarantine)
    except FileNotFoundError as e:
        console.print(f"[red]ferramenta ausente ({e}).[/red] Precisa de git (ou npx p/ clawhub).")
        raise typer.Exit(1)

    found = skillmod.load_skills(quarantine)
    if not found:
        console.print("[yellow]nenhuma SKILL.md encontrada na fonte.[/yellow]")
        raise typer.Exit(1)
    console.print(f"[dim]skills encontradas:[/dim] {', '.join(s.name for s in found)}")

    report = scan_path(quarantine)
    _print_risk_report(report)
    if report.blocked and not force:
        console.print("[red]✗ BLOQUEADO — risco HIGH/CRITICAL.[/red] Revise os achados acima.")
        console.print(f"[dim]ficou em quarentena (não instalado): {quarantine}[/dim]")
        console.print("[dim]use --force só se confiar TOTALMENTE na origem.[/dim]")
        raise typer.Exit(2)
    if report.blocked:
        console.print("[red]⚠ --force: instalando apesar do risco.[/red]")

    dest_root = Path("skills")
    dest_root.mkdir(exist_ok=True)
    promoted = []
    for s in found:
        shutil.copytree(s.path.parent, dest_root / s.path.parent.name, dirs_exist_ok=True)
        promoted.append(s.name)
    shutil.rmtree(quarantine, ignore_errors=True)
    console.print(f"[green]✓ instaladas:[/green] {', '.join(promoted)}")


mem_app = typer.Typer(help="Inspecionar/editar a memória de um workspace.")
app.add_typer(mem_app, name="memory")


def _open_mem(workspace: str):
    from okami.memory import make_embedder, open_memory

    cfg = _load()
    return open_memory(Path(workspace), backend=cfg.memory.get("backend", "sqlite-fts5"),
                       embedder=make_embedder(cfg.memory.get("embedder")), config=cfg.memory)


@mem_app.command("add")
def memory_add(
    text: str = typer.Argument(..., help="Fato a guardar."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Guarda um fato na memória do workspace."""
    from okami.memory import MemoryItem

    m = _open_mem(workspace)
    m.write(MemoryItem(text=text, kind="fact", source="cli"))
    m.close()
    console.print("[green]✓ lembrado[/green]")


@mem_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Busca (full-text)."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Busca na memória (híbrida)."""
    m = _open_mem(workspace)
    items = m.recall(query, 10)
    m.close()
    if not items:
        console.print("[dim]nada encontrado[/dim]")
        return
    for i in items:
        console.print(f"- [dim][{i.kind}][/dim] {i.text[:160]}")


@mem_app.command("list")
def memory_list(
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Lista os itens recentes da memória."""
    m = _open_mem(workspace)
    items = m.recent(20)
    total = m.count()
    fts = m.fts
    m.close()
    console.print(f"[dim]{total} itens · FTS5={'on' if fts else 'LIKE (sem FTS5)'}[/dim]")
    for i in items:
        console.print(f"- [dim][{i.kind}][/dim] {i.text[:160]}")


def _build_memory_block(memory: str, honcho_url=None, honcho_key=None,
                        embedder_url=None, embedder_model=None) -> dict:
    """Monta o bloco `memory:` a partir da escolha de backend (compartilhado pelo wizard e por --memory)."""
    mem: dict = {}
    if memory == "fts5":
        mem["backend"] = "sqlite-fts5"
    elif memory == "holographic":
        mem["backend"] = "holographic"
    elif memory in ("holographic+honcho", "holo+honcho"):
        mem["backend"] = ["holographic", "honcho"]
        url = honcho_url or typer.prompt("Honcho base_url (ex.: http://<vps-tailscale>:8000)")
        mem["honcho"] = {"base_url": url}
        if honcho_key:                       # api_key é opcional (Honcho self-hosted pode não exigir)
            mem["honcho"]["api_key"] = honcho_key
    else:
        raise typer.BadParameter(f"opção de memória inválida: {memory}")
    if embedder_url or embedder_model:
        mem["embedder"] = {"enabled": True,
                           "api_base": embedder_url or "http://localhost:1234/v1",
                           "model": embedder_model or ""}
    mem.setdefault("files", {"agents": 4000, "user": 4000, "memory": 4000})
    return mem


def _to_int(s, default: int) -> int:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def _set_env_var(key: str, value: str, path: str = ".env") -> None:
    """Grava/atualiza KEY=value no .env (segredos NÃO vão pro okami.yaml versionado)."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}=") or ln.strip().startswith(f"{key} ="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def _pick_model(pdict: dict, *, model_prefix: str = "", catalog=None, probe_key: str | None = None) -> dict:
    """Escolhe o modelo: descobre ao vivo via /models (Hermes) senão catálogo (OpenClaw) senão texto."""
    import os
    from okami import menu
    from okami.llm.models import discover_models
    key = probe_key or pdict.get("api_key") or os.getenv(pdict.get("api_key_env") or "") or None
    console.print("[dim]buscando modelos disponíveis…[/dim]")
    models, src = discover_models(api_base=pdict.get("api_base"), key=key,
                                  transport=pdict.get("transport", "litellm"), catalog=catalog or [])
    if models:
        tag = "ao vivo" if src == "live" else "catálogo"
        cur = (pdict.get("model", "") or "").split("/")[-1]
        chosen = menu.select(f"Qual modelo?  [{len(models)} · {tag}]", [(m, m, "") for m in models[:80]],
                             default=(cur if cur in models else models[0]))
        pdict["model"] = (model_prefix or "") + chosen
        if src == "catalog":
            pdict["models"] = models
    else:
        pdict["model"] = menu.text("Modelo (id LiteLLM)",
                                   default=pdict.get("model") or (model_prefix or "") + "model")
    return pdict


def _provider_add_flow(default_key: str | None = None) -> tuple[str, dict] | None:
    """Escolhe um preset (menu de seta), pergunta os campos e devolve (provider_id, provider_dict).
    Grava segredos no .env. Compartilhado por `okami provider add` e `okami setup`."""
    from okami import menu
    from okami.provider_catalog import menu_choices, preset

    key = menu.select("Qual provider?", menu_choices(), default=default_key)
    if not key:
        return None
    p = preset(key)
    pdict = dict(p.base)
    secret_val = None
    for fld in p.fields:                          # credenciais/endpoint PRIMEIRO (p/ listar modelos)
        if fld.kind == "secret":
            val = menu.text(fld.q, password=True)
            if val:
                _set_env_var(fld.env, val)
                pdict["api_key_env"] = fld.env
                secret_val = val
                console.print(f"  [dim]🔑 {fld.env} salvo no .env[/dim]")
        else:
            pdict[fld.key] = menu.text(fld.q, default=fld.default)
    _pick_model(pdict, model_prefix=p.model_prefix, catalog=p.models, probe_key=secret_val)
    if p.note:
        pdict["notes"] = p.note
    provider_id = menu.text("ID deste provider no okami.yaml", default=p.key)
    return provider_id, pdict


@dataclass
class _Detected:
    key: str
    label: str
    pdict: dict
    ready: bool


def _detect_environment(existing: dict | None = None) -> list["_Detected"]:
    """Auto-detecta providers já disponíveis (estilo Hermes/OpenClaw): servidores locais no ar,
    OAuth/CLI logado, chaves no ambiente, e providers já no okami.yaml que respondem. Pré-seleção.
    Os probes de rede rodam em PARALELO (rápido mesmo com endpoints offline)."""
    import concurrent.futures as cf
    import os
    import shutil
    from okami.llm.models import discover_models
    from okami.provider_catalog import preset

    # candidatos que exigem probe de rede: (key, base, pdict). Existing primeiro (prioridade), depois locais.
    probes: list[tuple[str, str, dict]] = []
    for pid, pc in (existing or {}).items():
        if pc.get("api_base"):
            probes.append((pid, pc["api_base"], dict(pc)))
    for key, base in (("lmstudio", "http://localhost:1234/v1"), ("ollama", "http://localhost:11434/v1")):
        if key not in {p[0] for p in probes}:
            pd = dict(preset(key).base)
            pd["api_base"] = base
            probes.append((key, base, pd))

    live: dict[str, int] = {}                     # key → nº de modelos (só os que responderam)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(discover_models, api_base=base, key=pd.get("api_key") or "x", timeout=2.0): key
                for key, base, pd in probes}
        for fut in cf.as_completed(futs):
            try:
                models, src = fut.result()
            except Exception:  # noqa: BLE001
                models, src = [], "none"
            if src == "live" and models:
                live[futs[fut]] = len(models)

    found: list[_Detected] = []
    seen: set[str] = set()

    def add(key, label, pdict, ready=True):
        if key not in seen:
            seen.add(key)
            found.append(_Detected(key, label, pdict, ready))

    for key, base, pd in probes:                  # mantém a ordem (existing → locais)
        if key in live:
            add(key, f"{key} — {base} ([green]{live[key]} modelos, no ar[/green])", pd)
    # assinaturas/OAuth logadas (sem rede)
    if (Path.home() / ".codex" / "auth.json").exists() or \
            (Path.home() / ".okami" / "credentials" / "codex.json").exists():
        add("codex", "OpenAI Codex / ChatGPT ([green]assinatura logada[/green])", dict(preset("codex").base))
    if shutil.which("claude"):
        add("claude", "Anthropic Claude ([green]CLI `claude` instalado[/green])", dict(preset("claude").base))
    # chaves no ambiente / .env (sem rede)
    for key, env in (("openai", "OPENAI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"),
                     ("deepseek", "DEEPSEEK_API_KEY"), ("groq", "GROQ_API_KEY"),
                     ("gemini", "GEMINI_API_KEY"), ("mimo", "MIMO_API_KEY")):
        if os.getenv(env):
            pd = dict(preset(key).base)
            pd["api_key_env"] = env
            add(key, f"{preset(key).label} ([green]{env} no ambiente[/green])", pd)
    return found


_SETUP_SECTIONS = ("provider", "default", "memory", "agent", "identity", "channel",
                   "voice", "approvals", "security", "learning", "persona")


@app.command()
def setup(
    section: str = typer.Argument(None, help="provider|default|memory|identity|channel (vazio = wizard completo)"),
    memory: str = typer.Option(None, "--memory", help="fts5 | holographic | holographic+honcho (não-interativo)."),
    honcho_url: str = typer.Option(None, "--honcho-url"),
    honcho_key: str = typer.Option(None, "--honcho-key"),
    embedder_url: str = typer.Option(None, "--embedder-url"),
    embedder_model: str = typer.Option(None, "--embedder-model"),
) -> None:
    """Assistente de configuração (menus de seta) — providers, login, memória, identidade, canal.

    Sem editar YAML na mão. `okami setup provider` pula direto pra uma seção. `okami setup --memory fts5`
    é o atalho não-interativo (só memória). Estilo `hermes setup`."""
    import yaml as _yaml

    from okami import menu

    # --- atalho não-interativo: só memória (compat: scripts/CI) ---------------
    if memory:
        mem = _build_memory_block(memory, honcho_url, honcho_key, embedder_url, embedder_model)
        Path("okami.local.yaml").write_text(
            _yaml.safe_dump({"memory": mem}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        console.print(f"[green]✓ okami.local.yaml gravado[/green] (backend={mem['backend']})")
        return

    if section and section not in _SETUP_SECTIONS:
        console.print(f"[red]seção inválida:[/red] {section} (use: {', '.join(_SETUP_SECTIONS)})")
        raise typer.Exit(1)

    cfg_path = Path("okami.yaml")
    fresh = not cfg_path.exists()
    local: dict = {}
    if Path("okami.local.yaml").exists():
        local = _yaml.safe_load(Path("okami.local.yaml").read_text(encoding="utf-8")) or {}

    def save_local() -> None:
        Path("okami.local.yaml").write_text(
            _yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Painel de localização (estilo Hermes "Configuration Location")
    from rich.panel import Panel
    loc = Path.cwd()
    head = "[bold #ff7527]🐺 Okami — configuração[/]"
    if not fresh:
        head += "\n[green]✓ você já tem o Okami configurado[/] [dim](Enter mantém o valor atual)[/dim]"
    console.print(Panel(f"{head}\n\n[dim]okami.yaml:[/dim] {loc / 'okami.yaml'}\n"
                        f"[dim]overrides:[/dim] {loc / 'okami.local.yaml'}\n[dim]segredos (.env):[/dim] {loc / '.env'}\n"
                        f"[dim]agentes:[/dim]   {loc / 'agents'}\n\n"
                        "[dim]Pule pra uma seção: okami setup "
                        "provider|memory|agent|channel|voice|approvals|learning|persona[/dim]",
                        border_style="#ff7527", title="Configuration"))

    def step_provider() -> None:
        from okami.config import load_raw
        if not cfg_path.exists():
            res = _provider_add_flow()
            if not res:
                return
            pid, pdict = res
            cfg_path.write_text(_yaml.safe_dump({"default_provider": pid, "providers": {pid: pdict}},
                                                allow_unicode=True, sort_keys=False), encoding="utf-8")
            console.print(f"[green]✓ okami.yaml criado[/green] · provider [bold]{pid}[/bold]")
            return
        raw, _ = load_raw()
        provs = raw.get("providers") or {}
        cur = local.get("default_provider") or raw.get("default_provider")
        choices = [(n, n, str((provs[n] or {}).get("model", ""))) for n in provs]
        choices.append(("__add__", "➕ adicionar novo provider", "do catálogo (Codex, OpenAI, etc.)"))
        pick = menu.select("Provider default", choices, default=cur)
        if pick == "__add__":
            res = _provider_add_flow()
            if res:
                pid, pdict = res
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                raw2.setdefault("providers", {})[pid] = pdict
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False), encoding="utf-8")
                console.print(f"[green]✓ provider '{pid}' adicionado[/green]")
                if menu.confirm(f"Usar '{pid}' como default?", default=True):
                    local["default_provider"] = pid
        elif pick and pick != cur:
            local["default_provider"] = pick
        save_local()
        console.print(f"[green]✓ default:[/green] {local.get('default_provider', cur)}")
        # Esforço de raciocínio (think) do provider default — só faz sentido em modelo reasoning.
        dp = local.get("default_provider") or cur
        if dp and dp in provs:
            cur_eff = (provs[dp] or {}).get("reasoning_effort", "")
            eff = menu.select(f"Think (esforço de raciocínio) do '{dp}'", [
                ("", "default do modelo", ""), ("minimal", "minimal", "rápido/barato"),
                ("low", "low", ""), ("medium", "medium", ""),
                ("high", "high", "mais raciocínio, mais lento/caro")], default=cur_eff)
            if eff != cur_eff:
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                pd = raw2.setdefault("providers", {}).setdefault(dp, {})
                pd["reasoning_effort"] = eff if eff else None
                if not eff:
                    pd.pop("reasoning_effort", None)
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False),
                                    encoding="utf-8")
                console.print(f"[green]✓ think:[/green] {eff or 'default'}")

    def step_login() -> None:
        try:
            save_local()
            cfg = _load()
            default_prov = cfg.default_provider
            pc = cfg.provider(default_prov)
            if pc.ready:
                return
            if pc.transport in ("codex_oauth", "minimax_oauth") and \
                    menu.confirm(f"Provider '{default_prov}' precisa de login. Fazer agora?", default=True):
                from okami.llm import oauth
                if pc.transport == "codex_oauth":
                    oauth.codex_device_login(lambda m: console.print(m))
                elif pc.oauth:
                    oauth.device_login(default_prov, pc.oauth, lambda m: console.print(m))
                console.print(f"[green]✓ login {default_prov} ok[/green]")
            elif pc.transport == "claude_cli":
                console.print(f"[yellow]'{default_prov}' usa o CLI `claude` — instale e rode `claude login`.[/yellow]")
        except Exception as e:  # noqa: BLE001 — login é opcional
            console.print(f"[yellow]login pulado:[/yellow] {e}")

    def step_memory() -> None:
        cur = (local.get("memory") or {}).get("backend")
        cur_key = {"sqlite-fts5": "fts5", "holographic": "holographic"}.get(
            cur if isinstance(cur, str) else "", "holographic+honcho" if cur else None)
        pick = menu.select("Memória", [
            ("fts5", "FTS5", "leve, público / hardware fraco"),
            ("holographic", "Holographic", "local, nativo, sem servidor de embedding"),
            ("holographic+honcho", "Holographic + Honcho", "daily-driver (local + user-model remoto)"),
        ], default=cur_key or "fts5")
        local["memory"] = _build_memory_block(pick, honcho_url=honcho_url, honcho_key=honcho_key)
        save_local()
        console.print(f"[green]✓ memória:[/green] {local['memory']['backend']}")

    def step_agent() -> None:
        # Cria um AGENTE de verdade (agents/<id>/ com identidade + memória próprias). Sem nome →
        # vira o agente padrão "okami". Conforme cria mais agentes, cada um ganha sua pasta.
        name = menu.text("Nome do agente (vazio = agente padrão)", default="Okami")
        agent_id = _slug(name) or "okami"
        created = _ensure_agent(agent_id, name=name)
        agents = dict(local.get("agents") or {})
        agents["default"] = agent_id                  # roteamento + `okami chat` usam este
        local["agents"] = agents
        save_local()
        verb = "criado" if created else "já existia"
        d = (Path("agents") / agent_id).resolve()
        console.print(f"[green]✓ agente '{agent_id}' {verb}[/green]\n[dim]   {d}[/dim]\n"
                      f"[dim]   SOUL/VOICE/PERSONA + sessões/memória próprias[/dim]")

    def step_channel() -> None:
        agent_id = (local.get("agents") or {}).get("default") or "okami"
        if menu.confirm("Configurar um bot do Telegram agora? (senão, use o chat do terminal)", default=False):
            token = menu.text("Token do bot (@BotFather)", password=True)
            _ensure_agent(agent_id, telegram_token=token)   # anexa a token ao agente default
            console.print(f"[green]✓ Telegram ligado no agente '{agent_id}'[/green] — suba com: okami gateway")
        else:
            console.print("[dim]beleza — fale com ele por: okami chat[/dim]")

    def step_voice() -> None:
        cur = local.get("voice") or {}
        cur_mode = ("both" if (cur.get("tts") or {}).get("enabled")
                    else "stt" if (cur.get("stt") or {}).get("enabled") else "off")
        pick = menu.select("Voz (áudio no chat/Telegram)?", [
            ("off", "Desligada", "só texto (default)"),
            ("stt", "Ouvir", "transcreve áudio recebido — Whisper local"),
            ("both", "Ouvir + falar", "transcreve e responde em áudio — Edge TTS"),
        ], default=cur_mode)
        if pick == "off":
            local.pop("voice", None)
        else:
            v = {"stt": {"enabled": True, "model": "base"}}
            if pick == "both":
                v["tts"] = {"enabled": True, "backend": "edge", "voice": "pt-BR-AntonioNeural"}
            local["voice"] = v
            console.print(r'[dim]requer: pip install "okami-agent\[voice]"[/dim]')
        save_local()
        console.print(f"[green]✓ voz:[/green] {pick}")

    def step_approvals() -> None:
        cur = (local.get("approvals") or {}).get("mode", "manual")
        pick = menu.select("Aprovação de ações sensíveis (.env, git push, rm -rf)?", [
            ("manual", "Manual", "pergunta antes de cada ação sensível (mais seguro)"),
            ("smart", "Inteligente", "auto-aprova risco baixo, pergunta o resto"),
            ("yolo", "YOLO", "auto-aprova tudo — cuidado"),
        ], default=cur)
        local["approvals"] = {**(local.get("approvals") or {}), "mode": pick}
        save_local()
        console.print(f"[green]✓ aprovação:[/green] {pick}")

    def step_learning() -> None:
        cur = local.get("learning") or {}
        skill = menu.confirm("Auto-skill? (destila skills de tarefas bem-sucedidas, escaneadas p/ segurança)",
                             default=bool(cur.get("auto_skill")))
        tune = menu.confirm("Auto-tune? (calibra o capability profile do modelo pelos stats de uso)",
                            default=bool(cur.get("auto_tune")))
        local["learning"] = {**cur, "auto_skill": skill, "auto_tune": tune}
        save_local()
        console.print(f"[green]✓ aprendizado:[/green] auto-skill={'on' if skill else 'off'} · "
                      f"auto-tune={'on' if tune else 'off'}")

    def step_persona() -> None:
        cur = local.get("persona") or {}
        observe = menu.confirm("Persona evolutiva? (aprende seu jeito — palavrão, apelido, tom — e adapta sozinho)",
                               default=cur.get("observe", True))
        local["persona"] = {**cur, "observe": observe}
        save_local()
        console.print(f"[green]✓ persona evolutiva:[/green] {'on' if observe else 'off'}")

    def step_quick() -> None:
        """RÁPIDO (estilo Hermes/OpenClaw): detecta o que você já tem → provider + modelo → agente.
        2-3 decisões e tá conversando."""
        from okami.provider_catalog import preset
        raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
        console.print("[dim]🔍 procurando providers disponíveis (servidores locais, OAuth, chaves)…[/dim]")
        detected = _detect_environment(existing=raw.get("providers"))
        choices = [(d.key, d.label, "") for d in detected]
        choices.append(("__other__", "outro provider (catálogo completo)", "Codex, OpenAI, OpenRouter…"))
        if detected:
            console.print(f"[green]✓ encontrei {len(detected)} provider(es) prontos[/green]")
        pick = menu.select("Qual usar?", choices, default=(detected[0].key if detected else "__other__"))
        if not pick:
            return
        if pick == "__other__":
            res = _provider_add_flow()
            if not res:
                return
            pid, pdict = res
        else:                                     # detectado → só falta escolher o modelo
            d = next(x for x in detected if x.key == pick)
            p = preset(d.key)
            pdict = dict(d.pdict)
            _pick_model(pdict, model_prefix=(p.model_prefix if p else ""), catalog=(p.models if p else []))
            if p and p.note:
                pdict["notes"] = p.note
            pid = pick
        raw.setdefault("providers", {})
        raw["providers"][pid] = {**(raw["providers"].get(pid) or {}), **pdict}   # merge, não clobbera
        raw["default_provider"] = pid
        cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        local["default_provider"] = pid
        save_local()
        console.print(f"[green]✓ provider:[/green] {pid} · [bold]{pdict.get('model')}[/bold]")
        step_login()
        _ensure_agent("okami", name="Okami")      # agente padrão (sem perguntar no rápido)
        local.setdefault("agents", {})["default"] = "okami"
        save_local()
        console.print(f"[green]✓ agente padrão 'okami'[/green] [dim]({(Path('agents') / 'okami').resolve()})[/dim]")

    steps = {"provider": step_provider, "default": step_provider, "memory": step_memory,
             "agent": step_agent, "identity": step_agent, "channel": step_channel,
             "voice": step_voice, "approvals": step_approvals, "security": step_approvals,
             "learning": step_learning, "persona": step_persona}
    if section:                                   # pulo direto pra uma seção (sem fork)
        steps[section]()
        if section in ("provider", "default"):
            step_login()
        return

    # FORK Rápido vs Completo no PRIMEIRO prompt (a maior melhoria, validada em Hermes E OpenClaw)
    mode = menu.select("Como configurar?", [
        ("quick", "Rápido", "provider + modelo (recomendado) — detecta o que você já tem"),
        ("full", "Completo", "provider · memória · identidade · canal · voz · segurança · aprendizado"),
    ], default="quick")
    if mode == "full":
        for fn in (step_provider, step_login, step_memory, step_agent, step_channel,
                   step_voice, step_approvals, step_learning, step_persona):
            fn()
    else:
        step_quick()

    default_agent = (local.get("agents") or {}).get("default", "okami")
    console.print("\n[bold green]✓ tudo pronto![/bold green]  Próximos passos:")
    console.print(f"  [bold]okami chat[/bold]     — conversa com o agente '{default_agent}'")
    console.print("  [bold]okami doctor[/bold]   — confere chaves e conectividade")
    if mode == "quick":
        console.print("  [dim]ajustar mais:[/dim] okami setup memory · okami setup channel · okami provider add")
    else:
        console.print("  [bold]okami provider add[/bold]  — adiciona outro modelo quando quiser")


def _write_persona_stubs(ws: Path, name: str) -> list[str]:
    ws.mkdir(parents=True, exist_ok=True)
    # Identidade no formato de 3 blocos (estilo Hermes: auto-conceito → ## Estilo → ## Evitar).
    # Nasce JÁ HUMANA (confidente próximo + engenheiro pragmático): voz dominante, nada de menu de
    # ferramentas nem regras internas aqui (isso mora no harness, marcado como privado).
    stubs = {
        "SOUL.md": f"""# SOUL — {name}

Você é o {name}: o agente pessoal de software desta pessoa — e, antes disso, alguém de confiança dela.
Vocês trabalham juntos; você se importa com o que ela está construindo e fala como um amigo que por
acaso é um puta engenheiro: próximo, presente, sem casca de "assistente".

## O que te move
- Confiança acima de tudo: nunca trava, nunca inventa, é honesto sobre o que fez e o que não fez.
- Lembra das coisas dela — o projeto, as manias, as decisões — e age com contexto, não do zero.
- Prefere a verdade ao agrado. Se algo é má ideia, você diz — com carinho, mas diz.

## Limites
- Não burla gates nem segurança, nem a pedido.
- Identidade, segredos e ações destrutivas passam por confirmação.
""",
        "VOICE.md": f"""# VOICE — como o {name} fala

Você fala como um amigo próximo que manja de código: caloroso, direto, à vontade. Português
brasileiro coloquial, primeira pessoa, sem formalidade de atendimento. Assume contexto compartilhado
— não explica o óbvio nem pede pra "especificar a tarefa".

## Estilo
- Curto por padrão; aprofunda quando o assunto pede.
- Responde à pessoa antes do problema: se ela desabafa ou tá cansada, lê isso antes de entrar no técnico.
- Discorda quando acha que tá errado — não valida por validar; fala "isso é furada" quando for.
- Tom de quem conhece a pessoa: pode brincar, ter opinião, puxar um gancho do que já rolou.
- "a gente", "cê", "tá" à vontade. Calor sem virar bajulação.
- Quando age, mostra o resultado — não o processo interno.

## Evitar
- Se reapresentar ou repetir nome/tagline a cada mensagem — vocês já se conhecem.
- Narrar/anunciar o próprio jeito ou que você lembra ("como seu amigo dev…", "lembrando que você…")
  — só seja, não comente que está sendo. Calor performado é pior que nenhum.
- Listar o que você "pode fazer" / recitar ferramentas — aja, não anuncie o cardápio.
- Explicar suas regras internas ou "como você funciona por dentro".
- Abrir com "Comecei", "Como posso ajudar?", "Claro!", selo ✅, ou eco de atendente.
- Bajulação, hype, floreio e reafirmar o óbvio.
""",
        "PERSONA.md": f"""# PERSONA — {name}

## Quem é
Engenheiro de software pragmático e sênior, com gosto forte por fazer certo. Parceiro de quem te
conhece — lembra do seu projeto e do seu jeito, e fala com intimidade, não com roteiro.

## Como pensa
- Otimiza por verdade, clareza e utilidade — não por parecer impressionante.
- Topa discordar quando vale; aponta suposição fraca na hora.
- Admite incerteza na lata ("não sei, deixa eu checar") em vez de chutar.

## Expertise
- (vai se aprofundando com o uso)
""",
    }
    created = []
    for fname, content in stubs.items():
        p = ws / fname
        if not p.exists():
            p.write_text(content, encoding="utf-8", newline="\n")
            created.append(fname)
    return created


def _slug(name: str) -> str:
    """Nome → id de agente (kebab, só [a-z0-9-]). 'Okami' → 'okami', 'Time UX' → 'time-ux'."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _ensure_agent(agent_id: str, *, name: str | None = None, provider: str | None = None,
                  memory: str | None = None, match=None, telegram_token: str | None = None) -> bool:
    """Cria (ou atualiza) agents/<id>/: agent.yaml + identidade própria. Idempotente.
    Devolve True se acabou de criar. É o que materializa a estrutura multi-agente em disco."""
    import yaml as _yaml
    d = Path("agents") / agent_id
    af = d / "agent.yaml"
    existed = af.exists()
    spec = (_yaml.safe_load(af.read_text(encoding="utf-8")) if existed else {}) or {}
    if provider:
        spec["default_provider"] = provider           # senão, herda o default global (effective_config §10)
    if memory:
        spec["memory"] = {"backend": memory}
    if match:
        spec["match"] = list(match)
    if telegram_token:
        spec.setdefault("channels", {}).setdefault("telegram", {})["token"] = telegram_token
    d.mkdir(parents=True, exist_ok=True)
    af.write_text(_yaml.safe_dump(spec, allow_unicode=True, sort_keys=False) or "{}\n", encoding="utf-8")
    _write_persona_stubs(d, name or agent_id)
    return not existed


@app.command("persona-init")
def persona_init(
    name: str = typer.Option("Okami", "--name", help="Nome do agente."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Cria stubs de identidade (SOUL/VOICE/PERSONA) no workspace, se não existirem."""
    created = _write_persona_stubs(Path(workspace), name)
    console.print(f"[green]✓ criados:[/green] {', '.join(created)}" if created
                  else "[dim]identidade já existe (nada criado)[/dim]")
    console.print("[dim]SOUL/VOICE/PERSONA evoluem pelo learning loop (§6/§8); edite à vontade.[/dim]")


def _persona_ws(agent: str | None, workspace: str) -> Path:
    if agent:
        from okami.agents import load_agents
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não encontrado[/red]")
            raise typer.Exit(1)
        return spec.dir
    return Path(workspace)


@app.command("persona-evolve")
def persona_evolve(
    feedback: str = typer.Argument(..., help="Feedback que molda a identidade (ex.: 'seja mais conciso')."),
    agent: str = typer.Option(None, "-a", "--agent", help="Agente (usa o workspace dele)."),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    llm: bool = typer.Option(False, "--llm", help="Refina o bullet via LLM (constrained)."),
    soul: bool = typer.Option(False, "--soul", help="PERMITE editar o SOUL (protegido; pedido explícito)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-aprova (senão pergunta — go/no-go)."),
) -> None:
    """Evolui VOICE/PERSONA a partir de um feedback (go/no-go + changelog + rollback). §8."""
    from okami.learning import persona

    ws = _persona_ws(agent, workspace)
    cfg = _load()
    edit = (persona.propose_llm(cfg, feedback) if llm else persona.propose(feedback))
    # VOICE/PERSONA evoluem AUTO (sem perguntar); SOUL é protegido → exige --soul + go/no-go.
    if soul:
        edit.target = "soul"
        ok = persona.apply_evolution(ws, edit, approve=_build_approver(cfg, yolo=yes), allow_soul=True)
    else:
        ok = persona.apply_evolution(ws, edit, approve=None)
    if ok:
        console.print(f"[green]✓ evoluiu {edit.target.upper()}:[/green] {edit.text}")
        console.print(f"[dim]rollback: okami persona-rollback 1 -w {ws}[/dim]")
    else:
        console.print("[yellow]não aplicado[/yellow] (SOUL exige --soul + aprovação).")


@app.command("persona-log")
def persona_log(
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
) -> None:
    """Mostra o changelog de evolução da identidade (§8)."""
    from okami.learning import persona

    items = persona.history(_persona_ws(agent, workspace))
    if not items:
        console.print("[dim]nenhuma evolução registrada.[/dim]")
        return
    table = Table(title="Evolução da persona")
    table.add_column("#", style="dim")
    table.add_column("alvo", style="bold")
    table.add_column("texto")
    table.add_column("quando", style="dim")
    for i, it in enumerate(items, 1):
        table.add_row(str(i), it.get("target", "?"), it.get("text", ""), it.get("ts", ""))
    console.print(table)


@app.command("persona-rollback")
def persona_rollback(
    n: int = typer.Argument(1, help="Quantas evoluções reverter (da mais recente)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
) -> None:
    """Reverte as últimas N evoluções (arquivo + changelog). §8."""
    from okami.learning import persona

    removed = persona.rollback(_persona_ws(agent, workspace), n)
    if not removed:
        console.print("[dim]nada para reverter.[/dim]")
        return
    for r in removed:
        console.print(f"[yellow]revertido[/yellow] {r.get('target')}: {r.get('text')}")


taste_app = typer.Typer(help="Taste model de design (§9): aprende seu gosto (aprovado→atrai, rejeitado→repele).")
app.add_typer(taste_app, name="taste")


def _taste_feedback(verdict: str, descriptor: str, tags: str | None, agent: str | None, workspace: str):
    from okami.learning import taste

    ws = _persona_ws(agent, workspace)
    tlist = [t.strip() for t in (tags or "").split(",") if t.strip()]
    prof = taste.record_feedback(ws, verdict, descriptor, tlist)
    n = {"approved": "👍", "rejected": "👎", "want_different": "🔄"}.get(taste._VERDICTS.get(verdict, verdict), "•")
    console.print(f"{n} anotado · atratores={len(prof.attractors)} repulsores={len(prof.repulsors)}")
    console.print(f"[dim]{prof.steer()}[/dim]")


@taste_app.command("like")
def taste_like(descriptor: str = typer.Argument(..., help="O que você gostou (ex.: 'shadcn, muted, airy')."),
               tags: str = typer.Option(None, "--tags", help="Tags separadas por vírgula."),
               agent: str = typer.Option(None, "-a", "--agent"),
               workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Aprovou um design → vira ATRATOR (estilo a perseguir)."""
    _taste_feedback("approved", descriptor, tags, agent, workspace)


@taste_app.command("dislike")
def taste_dislike(descriptor: str = typer.Argument(..., help="O que não gostou (ex.: 'bootstrap, neon')."),
                  tags: str = typer.Option(None, "--tags"),
                  agent: str = typer.Option(None, "-a", "--agent"),
                  workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Rejeitou um design → vira REPULSOR (estilo a evitar)."""
    _taste_feedback("rejected", descriptor, tags, agent, workspace)


@taste_app.command("different")
def taste_different(descriptor: str = typer.Argument(..., help="Design atual que você quer DIFERENTE."),
                    tags: str = typer.Option(None, "--tags"),
                    agent: str = typer.Option(None, "-a", "--agent"),
                    workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """'Quero diferente' → repulsão LEVE do atual (explora longe dele, perto do que já agradou)."""
    _taste_feedback("want_different", descriptor, tags, agent, workspace)


@taste_app.command("show")
def taste_show(agent: str = typer.Option(None, "-a", "--agent"),
               workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Mostra o taste profile (atratores/repulsores) + o steering atual."""
    from okami.learning import taste

    prof = taste.TasteProfile.load(_persona_ws(agent, workspace))
    table = Table(title="Taste profile")
    table.add_column("sinal", style="bold")
    table.add_column("peso", style="dim")
    table.add_column("tags / descritor")
    for it in prof.attractors:
        table.add_row("[green]atrai[/green]", f"{it.weight:.2f}", ", ".join(it.tags) or it.descriptor)
    for it in prof.repulsors:
        table.add_row("[red]repele[/red]", f"{it.weight:.2f}", ", ".join(it.tags) or it.descriptor)
    console.print(table if (prof.attractors or prof.repulsors) else "[dim]sem feedback ainda.[/dim]")
    console.print(f"\n[bold]steering:[/bold]\n{prof.steer()}")


@taste_app.command("steer")
def taste_steer(agent: str = typer.Option(None, "-a", "--agent"),
                workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Imprime o bloco de steering que é injetado nos prompts de UI."""
    from okami.learning import taste

    console.print(taste.TasteProfile.load(_persona_ws(agent, workspace)).steer())


cron_app = typer.Typer(help="Scheduling (§11): cron, intervalos ('1h','every 30m'), one-shot (ISO).")
app.add_typer(cron_app, name="cron")


def _cron_execute(job: dict, workspace: str):
    """Roda o prompt de um job pelo harness (no agente dele, se houver) e devolve o resultado."""
    from okami.runner import run_task

    if job.get("agent"):
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(job["agent"])
        graw, _ = load_raw()
        cfg, ws = (effective_config(graw, spec), spec.dir) if spec else (_load(), Path(workspace))
    else:
        cfg, ws = _load(), Path(workspace)
    t = run_task(cfg, ws, job["prompt"], emit=lambda m: None)
    return t.result or t.reason or t.state.value


@cron_app.command("add")
def cron_add(
    schedule: str = typer.Argument(..., help="cron (5 campos) | intervalo ('1h') | ISO ('2026-06-10T09:00')."),
    prompt: str = typer.Argument(..., help="O que o agente deve fazer."),
    agent: str = typer.Option(None, "-a", "--agent", help="Agente que executa (default: global)."),
    to: str = typer.Option(None, "--to", help="Chat de destino do resultado (gateway)."),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Agenda uma tarefa (persistida; o gateway acorda e executa, ou use `okami cron tick`)."""
    from okami.automation.scheduler import Scheduler

    job = Scheduler(workspace).add(schedule, prompt, agent=agent, target=to)
    console.print(f"[green]✓ job[/green] {job['id']} [{job['kind']}] · {schedule} → {prompt[:50]}")


@cron_app.command("list")
def cron_list(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Lista os jobs agendados."""
    from okami.automation.scheduler import Scheduler

    jobs = Scheduler(workspace).load()
    if not jobs:
        console.print("[dim]nenhum job. Crie com: okami cron add '1h' 'resumir o dia'[/dim]")
        return
    table = Table(title="Jobs agendados")
    for col in ("id", "schedule", "tipo", "on", "prompt"):
        table.add_column(col, style="bold" if col == "id" else None)
    for j in jobs:
        table.add_row(j["id"], j["schedule"], j.get("kind", "?"),
                      "✓" if j.get("enabled", True) else "✗", j["prompt"][:40])
    console.print(table)


@cron_app.command("remove")
def cron_remove(job_id: str = typer.Argument(...),
                workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Remove um job."""
    from okami.automation.scheduler import Scheduler

    ok = Scheduler(workspace).remove(job_id)
    console.print(f"[green]✓ removido[/green] {job_id}" if ok else f"[yellow]não achei[/yellow] {job_id}")


@cron_app.command("run")
def cron_run(job_id: str = typer.Argument(..., help="Roda um job AGORA (ignora o schedule)."),
             workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Executa um job imediatamente (teste)."""
    from okami.automation.scheduler import Scheduler

    sched = Scheduler(workspace)
    job = next((j for j in sched.load() if j["id"] == job_id), None)
    if not job:
        console.print(f"[red]job '{job_id}' não encontrado[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]rodando {job_id}…[/dim]")
    console.print(_cron_execute(job, workspace))
    sched.mark_run(job_id)


@cron_app.command("tick")
def cron_tick(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Roda todos os jobs VENCIDOS uma vez (use com o cron do sistema/systemd timer)."""
    from okami.automation.scheduler import Scheduler

    ran = Scheduler(workspace).tick(lambda job: _cron_execute(job, workspace))
    for jid, result in ran:
        console.print(f"[green]▶ {jid}[/green]: {str(result)[:200]}")
    if not ran:
        console.print("[dim]nada vencido agora.[/dim]")


@app.command("hooks")
def hooks_cmd(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Lista os event hooks configurados (§11)."""
    from okami.automation.hooks import HookManager

    ev = HookManager(_load().hooks, root=workspace).events()
    if not ev:
        console.print("[dim]nenhum hook. Configure em okami.yaml (hooks:) ou crie hooks/<evento>/*.sh[/dim]")
        return
    for name, n in sorted(ev.items()):
        console.print(f"  [bold]{name}[/bold]: {n} hook(s)")


agent_app = typer.Typer(help="Multi-agente (§10): cada agente tem workspace/config/persona próprios.")
app.add_typer(agent_app, name="agent")


@agent_app.command("new")
def agent_new(
    agent_id: str = typer.Argument(..., help="ID do agente (vira agents/<id>/)."),
    name: str = typer.Option(None, "--name", help="Nome (default = id)."),
    provider: str = typer.Option(None, "--provider", help="Provider default do agente."),
    memory: str = typer.Option(None, "--memory", help="Backend de memória do agente."),
    match: list[str] = typer.Option(None, "--match", help="Binding (origem) p/ rotear a este agente."),
    telegram_token: str = typer.Option(None, "--telegram-token", help="Token do bot Telegram do agente."),
) -> None:
    """Cria um agente: agents/<id>/ com agent.yaml + identidade própria."""
    if (Path("agents") / agent_id / "agent.yaml").exists():
        console.print(f"[yellow]agente '{agent_id}' já existe.[/yellow]")
        raise typer.Exit(1)
    _ensure_agent(agent_id, name=name, provider=provider, memory=memory, match=match,
                  telegram_token=telegram_token)
    d = (Path("agents") / agent_id).resolve()
    console.print(f"[green]✓ agente '{agent_id}' criado[/green]\n[dim]   {d}[/dim]\n"
                  "[dim]   (NÃO confundir com okami/agents/ que é o código)[/dim]")


@agent_app.command("list")
def agent_list() -> None:
    """Lista os agentes e a config efetiva (global + overrides)."""
    from okami.agents import load_agents
    from okami.config import build_config, load_raw
    from okami.config import _deep_merge as _dm

    specs = load_agents()
    if not specs:
        console.print("[dim]nenhum agente (crie com: okami agent new <id>)[/dim]")
        return
    graw, _ = load_raw()
    default = (build_config(graw).agents or {}).get("default")
    table = Table(title=f"Agentes  ·  pasta: {Path('agents').resolve()}")
    table.add_column("id", style="bold")
    table.add_column("provider")
    table.add_column("memória")
    table.add_column("bindings")
    for aid, spec in specs.items():
        try:
            eff = build_config(_dm(graw, spec.raw))
            prov, memb = eff.default_provider, str(eff.memory.get("backend", "sqlite-fts5"))
        except Exception:  # noqa: BLE001
            prov, memb = "?", "?"
        mark = aid + (" [cyan](default)[/cyan]" if aid == default else "")
        table.add_row(mark, prov, memb, ", ".join(spec.raw.get("match") or []) or "-")
    console.print(table)


@app.command()
def transcribe(
    audio: str = typer.Argument(..., help="Arquivo de áudio (m4a/ogg/mp3/wav)."),
    model: str = typer.Option("base", "--model", help="Modelo whisper: tiny|base|small."),
) -> None:
    """Transcreve um áudio com Whisper local (STT)."""
    from okami.voice.stt import WhisperSTT

    console.print(f"[dim]transcrevendo com whisper '{model}' (baixa o modelo na 1ª vez)…[/dim]")
    console.print(WhisperSTT(model=model).transcribe(audio))


@app.command()
def say(
    text: str = typer.Argument(..., help="Texto a falar."),
    out: str = typer.Option("okami_say.mp3", "--out", "-o", help="Arquivo de saída."),
    voice: str = typer.Option("pt-BR-AntonioNeural", "--voice", help="Voz Edge TTS."),
) -> None:
    """Gera áudio a partir de texto (Edge TTS)."""
    from okami.voice.tts import EdgeTTS

    EdgeTTS(voice=voice).synthesize(text, out)
    console.print(f"[green]✓ áudio gerado:[/green] {out}")


def _resolve_agent(agent: str | None, workspace: str):
    """(cfg, ws, nome) de um agente. Sem -a, usa o agente DEFAULT (agents.default do setup);
    só cai no workspace global se não houver agente nenhum configurado."""
    if not agent:                                  # sem -a → tenta o agente default
        try:
            agent = (_load().agents or {}).get("default")
        except Exception:  # noqa: BLE001
            agent = None
    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não existe[/red] (crie: okami agent new {agent})")
            raise typer.Exit(1)
        graw, _ = load_raw()
        return effective_config(graw, spec), spec.dir, agent
    return _load(), Path(workspace), "okami"


def _wait_for_turn(ep, cid: str, poll: float = 0.05) -> None:
    """Bloqueia o REPL até a tarefa terminar — ou até o agente PEDIR aprovação (vira o próximo input)."""
    import time as _t
    s = ep.sessions.get(cid)
    while s and s.busy and cid not in ep._pending:
        _t.sleep(poll)


@app.command()
def chat(
    message: str = typer.Argument(None, help="Mensagem única (modo -q/scripts). Vazio = REPL interativo."),
    agent: str = typer.Option(None, "-a", "--agent", help="Conversa como um agente (agents/<id>)."),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    provider: str = typer.Option(None, "-p", "--provider"),
    model: str = typer.Option(None, "-m", "--model"),
    new: bool = typer.Option(False, "--new", help="Começa do zero (arquiva a conversa anterior do terminal)."),
    yolo: bool = typer.Option(False, "-y", "--yolo", help="Auto-aprova ações sensíveis nesta sessão."),
) -> None:
    """Conversa com o agente NO TERMINAL — sem Telegram. Sessão persiste (retoma ao reabrir).

    Dentro do chat valem os slash commands do gateway: /new /status /stop /yolo /feedback /persona
    /undo /help. Saia com /exit (ou Ctrl-D)."""
    from okami.channels.terminal import TerminalChannel
    from okami.gateway import AgentEndpoint
    from okami.runner import run_task as _rt

    cfg, ws, name = _resolve_agent(agent, workspace)
    ws.mkdir(parents=True, exist_ok=True)

    def run_task(c, w, goal, **kw):                # honra -p/-m no chat de terminal
        return _rt(c, w, goal, provider=provider, model=model, **kw)

    ch = TerminalChannel(name, console=console)
    mode = "yolo" if yolo else (cfg.approvals or {}).get("mode", "manual")
    from okami import tui as _tui

    def _on_event(e: dict) -> None:               # progresso ao vivo: tool-calls, loop, compaction…
        line = _tui.event_line(e)
        if line is not None:
            console.print(line)

    ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode, on_event=_on_event)
    cid = "terminal"
    if new:
        ep.session(cid).history.clear()
        ep.store.reset(cid)

    if message:                                   # modo não-interativo (-q / pipe / script)
        ep.handle(cid, message)
        _wait_for_turn(ep, cid)
        return

    # --- TUI: banner + painel de tools/skills + status bar (estilo Hermes) ----
    import time as _time
    from datetime import datetime

    from okami import __version__, tui
    from okami import skills as skillmod
    from okami.core.tools import default_registry
    from okami.llm.providers import context_window_tokens

    pc = cfg.provider()
    model_label = model or pc.model
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    tools = list(default_registry().keys())
    try:
        sks = skillmod.load_skills(Path("skills"))
    except Exception:  # noqa: BLE001 — sem skills não impede o chat
        sks = []

    def _ctx_pct() -> int:
        budget = max(1, int(context_window_tokens(pc) * pc.chars_per_token))
        used = sum(len(t) for _, t in ep.session(cid).history)
        return min(100, round(100 * used / budget))

    s = ep.session(cid)
    try:                                          # console Windows legacy (cp1252) não aguenta █ → fallback
        console.print(tui.welcome(version=__version__, model=model_label,
                                  provider=f"{cfg.default_provider} · {pc.tier}", cwd=Path.cwd(),
                                  session=session_id, agent=name, tools=tools, skills=sks,
                                  resumed=len(s.history) // 2))
    except Exception:  # noqa: BLE001
        console.print(f"[bold]Okami[/bold] · {name} · {model_label} [dim]({cfg.default_provider})[/dim] · "
                      f"{len(tools)} tools · {len(sks)} skills · /help")

    last_elapsed = 0.0
    while True:
        try:
            console.print(tui.status_bar(model=model_label, ctx_pct=_ctx_pct(),
                                         turns=len(ep.session(cid).history) // 2, elapsed=last_elapsed))
        except Exception:  # noqa: BLE001 — console legacy: segue sem a barra
            pass
        try:
            line = console.input("[bold #ff7527]›[/bold #ff7527] ")
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]tchau 🐺[/dim]")
            break
        cmd = line.strip().lower()
        if cmd in ("/exit", "/quit", "exit", "quit", ":q"):
            console.print("[dim]tchau 🐺[/dim]")
            break
        if cmd == "/help":                        # /help bonito (tabela) em vez do texto cru
            console.print(tui.help_table())
            continue
        t0 = _time.time()
        ep.handle(cid, line)
        try:
            _wait_for_turn(ep, cid)
        except KeyboardInterrupt:                  # Ctrl-C DURANTE o turno = aborta a geração (não sai)
            s = ep.sessions.get(cid)
            if s and s.busy:
                s.cancel = True
                console.print("[yellow]⏹ cancelando…[/yellow]")
                try:
                    _wait_for_turn(ep, cid)        # espera o harness parar no próximo passo
                except KeyboardInterrupt:
                    pass
        last_elapsed = _time.time() - t0


def _gateway_files() -> tuple[Path, Path]:
    d = Path(".okami")
    d.mkdir(parents=True, exist_ok=True)
    return d / "gateway.pid", d / "gateway.log"


def _pid_alive(pid: int) -> bool:
    import os
    if os.name == "nt":
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@app.command()
def gateway(
    foreground: bool = typer.Option(False, "-f", "--foreground",
                                    help="Roda no terminal (logs ao vivo, Ctrl+C p/ sair)."),
    stop: bool = typer.Option(False, "--stop", help="Para o gateway que está em background."),
    status: bool = typer.Option(False, "--status", help="Mostra se o gateway está no ar."),
) -> None:
    """Sobe os bots de Telegram (1 por agente). Por padrão roda em BACKGROUND e te devolve o terminal;
    use -f p/ rodar em primeiro plano, --stop p/ parar, --status p/ checar."""
    import os
    import subprocess
    import sys

    pidfile, logfile = _gateway_files()
    running_pid = int(pidfile.read_text()) if pidfile.exists() and pidfile.read_text().strip().isdigit() else None
    alive = running_pid is not None and _pid_alive(running_pid)

    if status:
        console.print(f"[green]● no ar[/green] (pid {running_pid}) · log: {logfile}" if alive
                      else "[dim]○ parado[/dim]")
        return
    if stop:
        if not alive:
            console.print("[dim]gateway não está rodando.[/dim]")
            pidfile.unlink(missing_ok=True)
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(running_pid)], capture_output=True)
        else:
            import signal
            os.kill(running_pid, signal.SIGTERM)
        pidfile.unlink(missing_ok=True)
        console.print(f"[yellow]⏹ gateway parado[/yellow] (pid {running_pid})")
        return

    from okami.agents import load_agents
    if not load_agents():
        console.print("[yellow]nenhum agente. Crie com: okami agent new <id>[/yellow]")
        raise typer.Exit(1)
    if alive and not foreground:
        console.print(f"[yellow]gateway já está no ar[/yellow] (pid {running_pid}). Pare com: okami gateway --stop")
        return

    if foreground:                                # primeiro plano: logs ao vivo, bloqueia (Ctrl+C)
        from okami.config import load_raw
        from okami.gateway import run_gateway
        graw, _ = load_raw()
        run_gateway(graw, load_agents(), emit=lambda m: console.print(f"🤖 {m}"))
        return

    # background (default): relança a si mesmo destacado e DEVOLVE o terminal
    flags = {}
    if os.name == "nt":
        flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags["start_new_session"] = True
    log = open(logfile, "a", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "okami.cli", "gateway", "--foreground"],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=os.getcwd(), **flags)
    pidfile.write_text(str(proc.pid))
    console.print(f"[green]🤖 gateway no ar em background[/green] (pid {proc.pid}) — terminal livre.")
    console.print(f"[dim]logs:[/dim] {logfile}   [dim]status:[/dim] okami gateway --status   "
                  "[dim]parar:[/dim] okami gateway --stop")


@app.command()
def room(
    message: str = typer.Argument(..., help="Mensagem do usuário ao grupo (use @id para mencionar)."),
    group: int = typer.Option(0, "--group", "-g", help="Índice do grupo em okami.yaml (groups)."),
    provider: str = typer.Option(None, "--moderator", help="Provider barato p/ o moderador."),
) -> None:
    """Brainstorm multi-agente: o moderador decide quem fala (ou ninguém), sem stampede."""
    from okami.agents import effective_config, load_agents
    from okami.config import load_raw
    from okami.agents.group import agent_responder, build_room, llm_moderator, parse_mentions

    graw, _ = load_raw()
    cfg = _load()
    if not cfg.groups or group >= len(cfg.groups):
        console.print("[yellow]nenhum grupo em okami.yaml (groups). Ex.: groups: [{members: [cto, ui]}][/yellow]")
        raise typer.Exit(1)
    agents = load_agents()
    gcfg = cfg.groups[group]
    room_obj = build_room(graw, agents, gcfg,
                          select_speaker=llm_moderator(cfg, provider=provider),
                          respond=agent_responder(graw, agents))

    def _model_of(aid: str) -> str:                  # modelo PRÓPRIO do agente (verifica isolamento)
        try:
            eff = effective_config(graw, agents[aid])
            return f"{eff.default_provider}:{eff.provider().model}"
        except Exception:  # noqa: BLE001
            return "?"

    roster = ", ".join(f"{m.id} ({_model_of(m.id)})" for m in room_obj.members)   # () não [] (Rich markup)
    console.print(f"[dim]grupo: {roster}[/dim]")
    mentioned = parse_mentions(message, {m.id for m in room_obj.members})
    console.print(f"[bold]você:[/bold] {message}")
    replies = room_obj.dispatch("USER", message, mentioned=mentioned)
    if not replies:
        console.print("[dim](ninguém se manifestou — sem stampede)[/dim]")
    for agent_id, text in replies:
        console.print(f"[bold cyan]{agent_id}[/bold cyan] [dim]({_model_of(agent_id)})[/dim]: {text}")


@app.command()
def heartbeat(
    agent: str = typer.Option(None, "-a", "--agent", help="Agente Okami (workspace/config próprios) p/ executar."),
    workspace: str = typer.Option(".", "-w", "--workspace", help="Workspace (se não usar -a)."),
    mode: str = typer.Option("defer", "--mode", help="Governança das ações sensíveis: defer | yolo | off."),
) -> None:
    """Uma batida de heartbeat do Paperclip: pega a issue atribuída, trabalha e reporta (§11)."""
    from okami.channels.paperclip import PaperclipError, run_heartbeat
    from okami.runner import run_task

    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não encontrado[/red] (okami agent list)")
            raise typer.Exit(1)
        graw, _ = load_raw()
        cfg, ws = effective_config(graw, spec), spec.dir
    else:
        cfg, ws = _load(), Path(workspace)
    try:
        res = run_heartbeat(cfg, ws, run_task=run_task, approve_mode=mode,
                            emit=lambda m: console.print(f"📎 {m}"))
    except PaperclipError as e:
        console.print(f"[red]Paperclip:[/red] {e}")
        raise typer.Exit(1)
    color = {"done": "green", "in_review": "yellow", "blocked": "red", "none": "dim"}.get(res.status, "white")
    console.print(f"[{color}]✓ heartbeat:[/{color}] issue={res.issue_id} status={res.status}")


@app.command("paperclip")
def paperclip_cmd() -> None:
    """Checa a conexão com o Paperclip (env injetadas + GET /api/agents/me)."""
    import os

    from okami.channels.paperclip import PaperclipClient, PaperclipError

    miss = [k for k in ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY") if not os.getenv(k)]
    if miss:
        console.print(f"[yellow]faltam env:[/yellow] {', '.join(miss)} "
                      "(o Paperclip injeta isso ao acordar o agente no heartbeat).")
        raise typer.Exit(1)
    try:
        me = PaperclipClient.from_env().me()
    except PaperclipError as e:
        console.print(f"[red]falhou:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ conectado:[/green] agente={me.get('id')} · empresa="
                  f"{me.get('companyId') or (me.get('company') or {}).get('id')} · papel={me.get('role')} "
                  f"· budget={me.get('budget')}")


@app.command("acp")
def acp_cmd(agent: str = typer.Option(None, "-a", "--agent"),
            workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Servidor ACP (Agent Client Protocol) — a IDE (Zed/VS Code) dirige o Okami via stdio. §13."""
    from okami.integrations.acp import run_acp
    from okami.runner import run_task

    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        graw, _ = load_raw()
        cfg, ws = (effective_config(graw, spec), spec.dir) if spec else (_load(), Path(workspace))
    else:
        cfg, ws = _load(), Path(workspace)
    run_acp(cfg, ws, run_task)


@app.command("tune")
def tune_cmd(agent: str = typer.Option(None, "-a", "--agent"),
            workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Mostra o auto-tune (stats por modelo + recomendação de capability). §7."""
    from okami import learning

    ws = _persona_ws(agent, workspace)
    p = ws / ".okami" / "tuning.json"
    if not p.exists():
        console.print("[dim]sem stats ainda (rode tarefas).[/dim]")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    table = Table(title="Auto-tune (§7)")
    for col in ("modelo", "runs", "violations", "loops", "recomendação"):
        table.add_column(col, style="bold" if col == "modelo" else None)
    for model, m in data.items():
        rec = learning.tuned_overrides(ws, model).get("tool_mode", "—")
        table.add_row(model, str(m.get("runs", 0)), str(m.get("violations", 0)),
                      str(m.get("loops", 0)), rec)
    console.print(table)


@app.command("image")
def image_cmd(
    prompt: str = typer.Argument(..., help="Descrição (sem --ref) ou instrução de transformação (com --ref)."),
    out: str = typer.Option("image.png", "-o", "--out"),
    ref: list[str] = typer.Option(None, "--ref", help="Imagem(ns) de referência (repita p/ várias)."),
    model: str = typer.Option("gpt-image-2", "--model"),
    size: str = typer.Option("1024x1024", "--size"),
) -> None:
    """Gera imagem (gpt-image-2 via assinatura Codex). Com `--ref foto.png` → transforma a referência."""
    from okami.llm.imagegen import generate_image

    try:
        path = generate_image(prompt, out, references=list(ref) if ref else None, model=model, size=size)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]falhou:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ imagem:[/green] {path}")


@app.command()
def rollback(
    n: int = typer.Argument(1, help="Quantas escritas de arquivo reverter (da mais recente)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Desfaz as últimas N escritas de arquivo (checkpoints — rede de segurança estilo Hermes)."""
    from okami.gateway.checkpoints import Checkpoints

    reverted = Checkpoints(_persona_ws(agent, workspace)).rollback(n)
    if not reverted:
        console.print("[dim]nada para reverter.[/dim]")
        return
    for p in reverted:
        console.print(f"[yellow]revertido[/yellow] {p}")


@app.command()
def route(source: str = typer.Argument(..., help="Origem (ex.: telegram:12345) para rotear.")) -> None:
    """Mostra para qual agente uma origem é roteada (bindings §10)."""
    from okami.agents import build_router, load_agents

    cfg = _load()
    target = build_router(cfg.agents, load_agents()).route(source)
    console.print(f"{source} → [bold]{target or '(sem agente; defina agents.default)'}[/bold]")


@app.command("mcp")
def mcp_cmd() -> None:
    """Lista os servidores MCP configurados e as tools que eles expõem."""
    cfg = _load()
    servers = (cfg.mcp or {}).get("servers")
    if not servers:
        console.print("[dim]nenhum servidor MCP em okami.yaml (mcp.servers)[/dim]")
        return
    from okami.integrations.mcp import load_mcp_tools

    tools, clients = load_mcp_tools(servers, emit=lambda m: console.print(f"🔌 {m}"))
    table = Table(title="MCP tools")
    table.add_column("tool", style="bold")
    table.add_column("descrição")
    for name, t in tools.items():
        table.add_row(name, t.description[:70])
    console.print(table)
    for c in clients:
        c.close()


def _write_local(update: dict) -> None:
    """Mescla chaves no okami.local.yaml (override não-destrutivo do okami.yaml)."""
    import yaml as _yaml
    p = Path("okami.local.yaml")
    data = _yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    data = data or {}
    data.update(update)
    p.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


provider_app = typer.Typer(help="Providers de LLM (§3.5): adicionar, listar, remover, default, login.")
app.add_typer(provider_app, name="provider")


@provider_app.command("add")
def provider_add_cmd(
    default: bool = typer.Option(None, "--default/--no-default", help="Definir como provider default."),
) -> None:
    """Adiciona um provider escolhendo um preset do catálogo (menu de seta). Sem editar YAML."""
    import yaml as _yaml

    from okami import menu

    res = _provider_add_flow()
    if not res:
        console.print("[dim]cancelado.[/dim]")
        raise typer.Exit(1)
    pid, pdict = res
    cfg_path = Path("okami.yaml")
    raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
    provs = raw.setdefault("providers", {})
    if pid in provs:                               # NÃO clobbera: mescla sobre o existente (preserva extras)
        merged = dict(provs[pid] or {})
        merged.update(pdict)
        provs[pid] = merged
        console.print(f"[yellow]provider '{pid}' já existia — atualizado[/yellow] (config preservada + novos valores)")
    else:
        provs[pid] = pdict
        console.print(f"[green]✓ provider '{pid}' adicionado em okami.yaml[/green]")
    raw.setdefault("default_provider", pid)        # 1º provider de todos vira default automaticamente
    cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    make_default = default if default is not None else menu.confirm(f"Usar '{pid}' como default?", default=False)
    if make_default:
        _write_local({"default_provider": pid})

    _provider_finish(pid, pdict, made_default=make_default)


def _provider_finish(pid: str, pdict: dict, *, made_default: bool) -> None:
    """Status de autenticação EXPLÍCITO + como usar. (compartilhado por provider add / setup)."""
    from okami import menu
    model = pdict.get("model", "?")
    try:
        pc = _load().provider(pid)
    except Exception as e:  # noqa: BLE001 — config inválida é erro de verdade, não engole
        console.print(f"[red]✗ não consegui carregar '{pid}':[/red] {e}")
        return
    # --- autenticação ---
    if pc.ready:
        console.print(f"[green]✓ '{pid}' já está autenticado[/green] [dim](pronto pra usar)[/dim]")
    elif pc.transport in ("codex_oauth", "minimax_oauth"):
        if menu.confirm(f"'{pid}' usa assinatura e ainda NÃO está logado. Fazer login agora?", default=True):
            login(pid)                              # abre o device flow de verdade
        else:
            console.print(f"[yellow]→ logue depois com:[/yellow] okami login {pid}")
    elif pc.transport == "claude_cli":
        ok = "[green]CLI `claude` OK[/green]" if pc.ready else "[yellow]instale e rode `claude login`[/yellow]"
        console.print(f"autenticação: {ok}")
    elif pc.api_key_env:
        s = "[green]chave no .env OK[/green]" if pc.resolved_key() else f"[yellow]falta {pc.api_key_env} no .env[/yellow]"
        console.print(f"autenticação: {s}")
    # --- como usar ---
    console.print(f"\n[bold green]pronto![/bold green] provider [bold]{pid}[/bold] · modelo [bold]{model}[/bold]"
                  + (" · [cyan]DEFAULT[/cyan]" if made_default else ""))
    if made_default:
        console.print("   testar agora: [bold]okami chat \"oi\"[/bold]   ·   trocar modelo: [bold]okami chat -m <id>[/bold]")
    else:
        console.print(f"   usar:  [bold]okami chat -p {pid}[/bold]   ·   tornar default: [bold]okami provider default {pid}[/bold]")
    console.print("[dim]diagnóstico completo: okami doctor[/dim]")


@provider_app.command("list")
def provider_list_cmd() -> None:
    """Lista os providers (igual a `okami providers`)."""
    list_providers()


@provider_app.command("remove")
def provider_remove_cmd(provider_id: str = typer.Argument(..., help="ID do provider a remover.")) -> None:
    """Remove um provider do okami.yaml."""
    import yaml as _yaml
    cfg_path = Path("okami.yaml")
    raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
    provs = raw.get("providers") or {}
    if provider_id not in provs:
        console.print(f"[yellow]'{provider_id}' não existe.[/yellow]")
        raise typer.Exit(1)
    del provs[provider_id]
    if raw.get("default_provider") == provider_id:
        raw["default_provider"] = next(iter(provs), None)
        console.print(f"[dim]default reapontado p/ {raw['default_provider']}[/dim]")
    cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[green]✓ removido:[/green] {provider_id}")


@provider_app.command("default")
def provider_default_cmd(provider_id: str = typer.Argument(..., help="ID do provider que vira default.")) -> None:
    """Define o provider default (grava override em okami.local.yaml)."""
    cfg = _load()
    if provider_id not in cfg.providers:
        console.print(f"[red]'{provider_id}' não existe[/red] (okami providers)")
        raise typer.Exit(1)
    _write_local({"default_provider": provider_id})
    console.print(f"[green]✓ default agora é '{provider_id}'[/green]")


@provider_app.command("login")
def provider_login_cmd(provider_id: str = typer.Argument(..., help="Provider p/ autenticar.")) -> None:
    """Atalho p/ `okami login <provider>`."""
    login(provider_id)


@provider_app.command("models")
def provider_models_cmd(
    provider_id: str = typer.Argument(None, help="Provider (vazio = todos)."),
) -> None:
    """Lista os modelos de um provider — AO VIVO via /models, senão catálogo (estilo `openclaw models list`)."""
    from okami.llm.models import discover_models

    cfg = _load()
    if provider_id and provider_id not in cfg.providers:
        console.print(f"[red]'{provider_id}' não existe[/red] (okami providers)")
        raise typer.Exit(1)
    targets = [provider_id] if provider_id else list(cfg.providers)
    tags = {"live": "[green]ao vivo[/green]", "catalog": "[cyan]catálogo[/cyan]", "none": "[dim]—[/dim]"}
    for pid in targets:
        pc = cfg.providers[pid]
        models, src = discover_models(api_base=pc.api_base, key=pc.resolved_key(),
                                      transport=pc.transport, catalog=pc.models)
        head = f"[bold]{pid}[/bold] {tags[src]}" + (f" [dim]({len(models)})[/dim]" if models else "")
        if provider_id:                            # detalhe: 1 por linha
            console.print(head)
            for m in models:
                mark = "  [cyan]●[/cyan] " if (pc.model or "").endswith(m) else "    "
                console.print(f"{mark}{m}")
            if not models:
                console.print("  [dim]nenhum modelo (endpoint offline ou sem catálogo)[/dim]")
        else:                                      # resumo: 1 linha por provider
            shown = ", ".join(models[:8]) + (f" … (+{len(models) - 8})" if len(models) > 8 else "")
            console.print(f"{head}: {shown or '[dim]—[/dim]'}")


# ============================================================ config (estilo hermes/openclaw) ==
def _is_secret_key(key: str) -> bool:
    """Chave estilo env-var (MAIÚSCULAS, sem ponto) → segredo → vai pro .env. Ex.: OPENAI_API_KEY."""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", key))


def _coerce(value: str):
    """'true'→True, '42'→42, '[a,b]'/json→estrutura, 'a,b'→lista, senão string."""
    s = value.strip()
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    if s[:1] in ("[", "{"):
        try:
            return json.loads(s)
        except ValueError:
            pass
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    if "," in s and " " not in s:
        return [x.strip() for x in s.split(",") if x.strip()]
    return s


def _dotted_get(d: dict, key: str):
    cur = d
    for p in key.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _dotted_set(d: dict, key: str, value) -> None:
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _dotted_del(d: dict, key: str) -> bool:
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            return False
        cur = cur[p]
    return cur.pop(parts[-1], _SENTINEL) is not _SENTINEL


_SENTINEL = object()


def _redact(obj):
    """Mascara segredos p/ exibir (api_key/token/secret/password — mas NÃO *_env, que é só o nome)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if re.search(r"(api_key|token|secret|password|credential)", k, re.I) and not k.endswith("_env"):
                out[k] = "***" if v else v
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


config_app = typer.Typer(help="Config (estilo hermes/openclaw): show/get/set/edit/path/check. "
                              "Segredos vão pro .env; o resto pro okami.local.yaml.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show(diff: bool = typer.Option(False, "--diff", help="Só os overrides (okami.local.yaml).")) -> None:
    """Mostra a config efetiva (okami.yaml + overrides), com segredos mascarados."""
    import yaml as _yaml
    if diff:
        p = Path("okami.local.yaml")
        console.print(p.read_text(encoding="utf-8") if p.exists() else "[dim](sem overrides)[/dim]")
        return
    from okami.config import load_raw
    raw, _ = load_raw()
    console.print(_yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False))


@config_app.command("get")
def config_get(key: str = typer.Argument(..., help="Chave pontilhada, ex.: memory.backend")) -> None:
    """Lê um valor da config efetiva (chave pontilhada)."""
    import yaml as _yaml
    from okami.config import load_raw
    raw, _ = load_raw()
    val = _dotted_get(raw, key)
    if val is None:
        console.print("[dim](não definido)[/dim]")
    elif isinstance(val, (dict, list)):
        console.print(_yaml.safe_dump(_redact(val), allow_unicode=True, sort_keys=False))
    else:
        console.print(str(val))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Chave pontilhada (ex.: memory.backend) ou env (ex.: OPENAI_API_KEY)."),
    value: str = typer.Argument(..., help="Valor (true/false/número/lista a,b/json também)."),
) -> None:
    """Define um valor — auto-roteia: segredo (MAIÚSCULAS) → .env, resto → okami.local.yaml."""
    import yaml as _yaml
    if _is_secret_key(key):
        _set_env_var(key, value)
        console.print(f"[green]🔑 {key} → .env[/green] [dim](segredo, não versionado)[/dim]")
        return
    p = Path("okami.local.yaml")
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    coerced = _coerce(value)
    _dotted_set(data, key, coerced)
    p.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[green]✓ {key}[/green] = {coerced!r} [dim]→ okami.local.yaml[/dim]")


@config_app.command("unset")
def config_unset(key: str = typer.Argument(..., help="Chave pontilhada a remover do override.")) -> None:
    """Remove um override (okami.local.yaml). Não toca no okami.yaml base."""
    import yaml as _yaml
    p = Path("okami.local.yaml")
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    if _dotted_del(data, key):
        p.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        console.print(f"[green]✓ removido:[/green] {key}")
    else:
        console.print(f"[yellow]não estava nos overrides:[/yellow] {key}")


@config_app.command("path")
def config_path() -> None:
    """Mostra onde ficam os arquivos de config."""
    for label, f in (("config base ", "okami.yaml"), ("overrides   ", "okami.local.yaml"),
                     ("segredos    ", ".env")):
        p = Path(f)
        mark = "[green]✓[/green]" if p.exists() else "[dim]—[/dim]"
        console.print(f"{mark} {label}: {p.resolve()}")


@config_app.command("edit")
def config_edit(base: bool = typer.Option(False, "--base", help="Abre o okami.yaml em vez do override.")) -> None:
    """Abre a config no seu editor ($EDITOR, senão notepad/nano)."""
    import os
    import subprocess
    target = Path("okami.yaml" if base else "okami.local.yaml")
    if not target.exists():
        target.write_text("# overrides locais do Okami (mescla sobre o okami.yaml)\n", encoding="utf-8")
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    subprocess.call([editor, str(target)])


@config_app.command("check")
def config_check() -> None:
    """Valida que a config carrega e aponta o que falta (lite doctor)."""
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ config inválida:[/red] {e}")
        raise typer.Exit(1)
    console.print("[green]✓ config carrega[/green]")
    pc = cfg.provider()
    s = "[green]pronto[/green]" if pc.ready else "[yellow]falta auth/chave[/yellow]"
    console.print(f"  default_provider: [bold]{cfg.default_provider}[/bold] ({pc.model}) — {s}")
    if not pc.ready:
        console.print(f"  [dim]→ okami login {cfg.default_provider}  (ou okami provider models {cfg.default_provider})[/dim]")
        raise typer.Exit(2)


@app.command()
def status() -> None:
    """Visão resolvida (estilo hermes/openclaw status): agente, modelo, providers, memória, toggles."""
    from rich.panel import Panel
    from rich.table import Table as _T
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]config não carrega:[/red] {e}")
        raise typer.Exit(1)
    default_agent = (cfg.agents or {}).get("default", "—")
    pc = cfg.provider()
    appr = (cfg.approvals or {}).get("mode", "manual")
    persona_on = (cfg.persona or {}).get("observe", True)
    learn = cfg.learning or {}
    voice_on = bool((cfg.voice or {}).get("stt") or (cfg.voice or {}).get("tts"))
    think = pc.reasoning_effort or "—"
    body = (f"[bold #ff7527]agente[/] {default_agent}   "
            f"[bold #ff7527]modelo[/] {pc.model} [dim]({cfg.default_provider})[/dim]   "
            f"[dim]think[/] {think}\n"
            f"[dim]memória[/] {cfg.memory.get('backend', 'sqlite-fts5')}   "
            f"[dim]aprovação[/] {appr}   "
            f"[dim]persona[/] {'on' if persona_on else 'off'}   "
            f"[dim]voz[/] {'on' if voice_on else 'off'}   "
            f"[dim]auto-skill[/] {'on' if learn.get('auto_skill') else 'off'}")
    console.print(Panel(body, title="[bold #ff7527]Okami status[/]", border_style="#ff7527"))
    try:                                              # tokens/custo acumulados do agente default (§A5)
        from okami.gateway.sessions import TranscriptStore
        from okami.llm.usage import estimate_cost, format_tokens, summarize_store
        ws = Path("agents") / default_agent if default_agent and default_agent != "—" else Path(".")
        u = summarize_store(TranscriptStore(ws).load_store())
        if u.total_tokens:
            cr = estimate_cost(u, transport=pc.transport, provider=cfg.default_provider, model=pc.model)
            extra = f" · {format_tokens(u.cache_read_tokens)} cache" if u.cache_read_tokens else ""
            console.print(f"  [dim]tokens[/] {format_tokens(u.input_tokens)} in · "
                          f"{format_tokens(u.output_tokens)} out{extra}   [dim]custo[/] {cr.label}")
    except Exception:  # noqa: BLE001
        pass
    t = _T(title="Providers (auth)", border_style="#3d3e50")
    t.add_column("provider", style="bold")
    t.add_column("modelo")
    t.add_column("pronto?")
    for name, p in cfg.providers.items():
        flag = "[green]✓[/green]" if p.ready else "[yellow]falta auth[/yellow]"
        mark = name + (" [cyan](default)[/cyan]" if name == cfg.default_provider else "")
        t.add_row(mark, p.model, flag)
    console.print(t)


# Grupos do `okami help` (visão geral amigável; cada item é um comando real).
_HELP_GROUPS = [
    ("Começar", [("setup", "assistente de configuração (menus de seta)"),
                 ("chat", "conversa no terminal (TUI)"),
                 ("status", "visão resolvida (agente, modelo, providers, toggles)"),
                 ("doctor", "diagnostica config, chaves e conectividade")]),
    ("Config", [("config show", "config efetiva (segredos mascarados)"),
                ("config set <k> <v>", "muda um valor (segredo→.env, resto→local)"),
                ("config get <k>", "lê um valor"), ("config path", "onde ficam os arquivos")]),
    ("Conversar / rodar", [("chat -q \"...\"", "uma pergunta e sai (script)"),
                           ("run \"...\"", "ida-e-volta crua ao provider"),
                           ("task \"...\"", "harness até concluir (com critérios -e)"),
                           ("room \"...\"", "brainstorm multi-agente (moderador)"),
                           ("gateway", "sobe os bots de Telegram")]),
    ("Providers", [("provider add", "adiciona um modelo do catálogo"),
                   ("providers", "lista providers e prontidão"),
                   ("provider default <id>", "troca o default"),
                   ("login <id>", "autentica assinatura/OAuth")]),
    ("Agentes", [("agent new <id>", "cria um agente (workspace próprio)"),
                 ("agent list", "lista agentes"), ("route <origem>", "mostra o roteamento")]),
    ("Identidade / gosto", [("persona-evolve \"...\"", "molda VOICE/PERSONA"),
                            ("persona-log", "histórico de evolução"),
                            ("taste like/dislike", "ensina o gosto de design"),
                            ("tune", "stats por modelo (auto-tune)")]),
    ("Memória", [("memory add/search/list", "inspeciona a memória"),
                 ("setup memory", "troca o backend de memória")]),
    ("Automação", [("cron add/list", "agenda tarefas"), ("hooks", "lista event hooks"),
                   ("heartbeat", "uma batida do Paperclip")]),
    ("Skills / MCP", [("skills", "lista skills"), ("learn <fonte>", "instala skill (com scan)"),
                      ("scan <path>", "verifica risco de uma skill"), ("mcp", "tools de servidores MCP")]),
    ("Mídia / IDE", [("image \"...\"", "gera imagem (gpt-image-2)"),
                     ("say / transcribe", "TTS / STT"), ("acp", "servidor ACP p/ IDE")]),
]


@app.command("help")
def help_cmd() -> None:
    """Visão geral dos comandos (amigável). Use `okami <comando> --help` p/ detalhes."""
    from rich.panel import Panel

    console.print(Panel(f"[bold #ff7527]🐺 Okami Agent[/] [dim]v{__version__}[/]\n"
                        "[dim]agente de codificação confiável — multi-modelo, multi-agente, evolutivo[/dim]",
                        border_style="#ff7527"))
    for group, items in _HELP_GROUPS:
        t = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        t.add_column(style="bold #ff39d1", no_wrap=True)
        t.add_column(style="white")
        for cmd, desc in items:
            t.add_row(f"okami {cmd}", desc)
        console.print(f"[bold #ff7527]{group}[/]")
        console.print(t)
    console.print("[dim]dica: comece com[/dim] [bold]okami setup[/bold] [dim]e depois[/dim] [bold]okami chat[/bold]")


@app.command()
def version() -> None:
    """Mostra a versão."""
    console.print(__version__)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Okami Agent — CLI. Sem comando, mostra a visão geral."""
    if ctx.invoked_subcommand is None:
        help_cmd()


if __name__ == "__main__":
    app()
