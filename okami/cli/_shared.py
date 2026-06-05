"""Helpers compartilhados da CLI (sem comandos) — usados por okami.cli.commands.*."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import typer

from okami.config import OkamiConfig, load_config
from okami.core import TaskState
from okami.cli._app import console


def _persona_ws(agent: str | None, workspace: str) -> Path:
    """Resolve o workspace de um agente (agents/<id>) ou o caminho dado (compartilhado)."""
    if agent:
        from okami.agents import load_agents
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não encontrado[/red]")
            raise typer.Exit(1)
        return spec.dir
    return Path(workspace)


def _load() -> OkamiConfig:
    try:
        return load_config()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Falha ao carregar config:[/red] {e}")
        raise typer.Exit(1)


def _ping_models(api_base: str, timeout: float = 6.0) -> tuple[bool, str]:
    url = api_base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", [])]
        return True, f"{len(ids)} modelos" + (f" (ex.: {ids[0]})" if ids else "")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, str(e)


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
    from okami.core.safe_io import secure_write_yaml
    secure_write_yaml(p, data)              # atômico + backup + .last-good (P1.2)


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

    from okami.core.tools import sanitized_env
    env = sanitized_env()                 # fetch (npx/git) SEM segredos — clawhub roda código (P1.5)
    dest.mkdir(parents=True, exist_ok=True)
    local = Path(source)
    if local.exists():  # caminho local
        shutil.copytree(local, dest / local.name, dirs_exist_ok=True)
        return
    if source.startswith("clawhub:"):  # ClawHub (executa npx — gated por --allow-exec no learn)
        subprocess.call(["npx", "clawhub", "install", source.split(":", 1)[1]], cwd=str(dest), env=env)
        return
    url = f"https://github.com/{source}.git" if re.match(r"^[\w.-]+/[\w.-]+$", source) else source
    subprocess.call(["git", "clone", "--depth", "1", url], cwd=str(dest), env=env)


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


def _set_env_var(key: str, value: str, path: str | None = None) -> None:
    """Grava/atualiza KEY=value no .env — escrita ATÔMICA + 0600 (segredo só p/ o dono).

    path=None → .env GLOBAL (~/.okami/.env): configura uma vez, vale em qualquer workspace."""
    import os
    import tempfile
    from okami.config import global_env_path
    p = Path(path) if path else global_env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
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
    data = "\n".join(out) + "\n"
    # tmp no mesmo diretório → os.replace é atômico (sem janela de arquivo meia-escrita/world-readable).
    fd, tmp = tempfile.mkstemp(dir=str(p.parent if str(p.parent) else "."), prefix=".env.", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, 0o600)                       # 0600 ANTES de escrever o segredo
        except (AttributeError, OSError):              # Windows/sem suporte → segue
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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


def _write_local(update: dict) -> None:
    """Mescla chaves no okami.local.yaml (override não-destrutivo do okami.yaml) — escrita durável."""
    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = Path("okami.local.yaml")
    data = read_yaml_resilient(p, default={})       # recupera de backup se o atual estiver corrompido
    data.update(update)
    secure_write_yaml(p, data)                       # atômico + backup rotacionado + .last-good (P1.2)


