"""Helpers compartilhados da CLI (sem comandos) — usados por okami.cli.commands.*."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import typer

from okami.config import config_dir
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


_MISSING_CONFIG_HINT = (
    "Rode:  [bold]okami setup[/bold]  (ou [bold]okami setup provider[/bold] para só o essencial)"
)


def _load_or_offer_setup() -> OkamiConfig:
    """Como `_load()`, mas quando a config está AUSENTE (não outros erros) convida a rodar o wizard
    na hora — paridade Hermes (main.py:2279-2306 "Run setup now? [Y/n]"). Interativo → pergunta e, se
    sim, roda `okami setup` inline e recarrega; não-interativo (pipe/CI) → orientação concreta + exit 1
    sem perguntar nada (nunca trava esperando input que não vem).

    De propósito NÃO mora em `_load()` — `_load()` é usado por ~30 comandos (inclusive helpers de
    view tipo `_summary_fields`) que precisam continuar falhando limpo sem abrir um wizard no meio do
    render. Só o caminho de "resolver o agente pra rodar" (chat/media/promptsize via `_resolve_agent`)
    oferece o convite."""
    try:
        return load_config()
    except FileNotFoundError as e:
        return _offer_setup(e)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Falha ao carregar config:[/red] {e}")
        raise typer.Exit(1)


def _offer_setup(err: Exception) -> OkamiConfig:
    from okami import menu

    if not menu._interactive():
        console.print(f"[red]Falha ao carregar config:[/red] {err}")
        console.print(f"[dim]{_MISSING_CONFIG_HINT}[/dim]")
        raise typer.Exit(1)
    console.print(f"[yellow]Nenhuma config encontrada[/yellow] — {err}")
    if menu.confirm("Rodar `okami setup` agora?", default=True):
        from okami.cli.commands.setup import setup as cmd_setup
        cmd_setup(section=None, memory=None, honcho_url=None, honcho_key=None,
                  embedder_url=None, embedder_model=None)
        return load_config()
    console.print(f"[dim]{_MISSING_CONFIG_HINT}[/dim]")
    raise typer.Exit(1)


def _ping_models(api_base: str, timeout: float = 6.0) -> tuple[bool, str, list[str]]:
    """Pinga /models. Devolve (ok, msg, ids) — os `ids` deixam o doctor (item 15b) distinguir
    "endpoint off" de "modelo errado/typo" via model_present. Lista vazia quando não há ids/no erro."""
    url = api_base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", [])]
        return True, f"{len(ids)} modelos" + (f" (ex.: {ids[0]})" if ids else ""), ids
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, str(e), []


def _collect_channels():
    """Canais p/ a policy/status: bloco global `channels` + por-agente (agent.yaml), best-effort."""
    from okami.config import load_raw
    from okami.core.policy import collect_channels
    raw, _ = load_raw()
    try:
        from okami.agents import load_agents
        agents = load_agents()
    except Exception:  # noqa: BLE001
        agents = {}
    return raw, collect_channels(raw, agents)


def _disk_renderable(cfg, *, root: str = ".", top: int = 6, as_meters: bool = False):
    """Renderable da seção `◆ Disco`: uso por área (bytes/arquivos), total e aviso de quota.

    Compartilhado por `status` e `doctor`. `as_meters=True` desenha BARRAS de uso (proporcionais à
    maior área, cor por quota); senão uma tabela. Devolve um Text discreto se o .okami/ está vazio."""
    from rich.text import Text

    from okami.cli import _ui
    from okami.core.maintenance import disk_report, fmt_bytes
    rep = disk_report(root, retention=getattr(cfg, "retention", None))
    areas = rep["areas"]
    if not areas:
        return Text("sem dados ainda — .okami/ vazio (nada a podar)", style=_ui.MUTE)
    rows = sorted(areas.items(), key=lambda kv: kv[1]["bytes"], reverse=True)[:top]
    peak = max((a["bytes"] for _, a in rows), default=1) or 1

    total = Text()
    total.append(f"total {fmt_bytes(rep['bytes_total'])}", style=f"bold {_ui.FG}")
    if rep["over_quota"]:
        total.append(f"   ▲ {len(rep['over_quota'])} acima da quota — okami clean --deep", style=_ui.AMBER)
    else:
        total.append("   · okami clean --deep poda o que envelheceu", style=_ui.MUTE)

    if as_meters:                                     # barras: comprimento ∝ tamanho; cor por quota
        mrows = []
        for key, a in rows:
            color = _ui.RED if a["over_quota"] else (_ui.MAGENTA if a["prunable"] else _ui.DIM)
            flag = _ui.badge("warn", "quota") if a["over_quota"] else Text("durável", style=_ui.DIM) \
                if not a["prunable"] else Text("")
            mrows.append((key, a["bytes"] / peak, fmt_bytes(a["bytes"]), flag, color))
        meters = _ui.meter_rows(mrows, bar_width=12, label_w=12)
        return _ui.stack(meters, total)

    t = _ui.data_table(("área", {"style": f"bold {_ui.FG}", "no_wrap": True}),
                       ("tam.", {"justify": "right", "style": _ui.MAGENTA, "no_wrap": True}),
                       ("arquivos", {"justify": "right", "style": _ui.MUTE, "no_wrap": True}),
                       ("", {"no_wrap": True}))
    for key, a in rows:
        flag = _ui.badge("warn", f"> quota {int(a['quota_mb'])}MB") if a["over_quota"] else (
            Text("durável", style=_ui.DIM) if not a["prunable"] else Text(""))
        t.add_row(key, fmt_bytes(a["bytes"]), str(a["files"]), flag)
    return _ui.stack(t, total)


def _persist_always_allow(category: str) -> None:
    """Adiciona uma categoria ao approvals.always_allow em okami.local.yaml (cross-sessão)."""
    import yaml as _yaml

    p = config_dir() / "okami.local.yaml"
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
    # TIMEOUT + stdin=DEVNULL em TODA busca de rede (paridade Hermes skills_hub): sem isto, um npx/clone
    # lento ou que PEDE credencial pendurava p/ sempre, o anti-stall resetava a cada erro variado e o
    # agente re-tentava → ~59min sem progresso (transcript real). Agora falha LIMPO e rápido.
    if source.startswith("clawhub:"):  # ClawHub (executa npx — gated por --allow-exec no learn)
        try:
            subprocess.run(["npx", "clawhub", "install", source.split(":", 1)[1]], cwd=str(dest), env=env,
                           stdin=subprocess.DEVNULL, timeout=120)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"timeout (120s) instalando '{source}' via clawhub — rede lenta ou o pacote travou.")
        return
    url = f"https://github.com/{source}.git" if re.match(r"^[\w.-]+/[\w.-]+$", source) else source
    try:
        r = subprocess.run(["git", "clone", "--depth", "1", url], cwd=str(dest), env=env,  # noqa: S603,S607
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timeout (120s) clonando '{source}' — repo lento/inacessível ou pediu credencial.")
    if r.returncode != 0:                 # SEM checar o exit, repo inexistente/privado/sem rede virava o erro
        _tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["sem detalhe"]   # ENGANOSO "nenhuma SKILL.md"
        raise RuntimeError(f"git clone de '{source}' falhou: {_tail[0]}")


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
    """Grava/atualiza KEY=value no .env — escrita ATÔMICA + 0600. Delega p/ a fonte ÚNICA
    `config.set_env_secret` (a mesma lógica que a tool store_secret usa — sem duplicar segredo-escrita).

    path=None → .env GLOBAL ($OKAMI_HOME/.env, default ~/.okami/.env): configura uma vez, vale em qualquer workspace."""
    from okami.config import set_env_secret
    set_env_secret(key, value, path=path)


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
    from okami.home import read_path
    if (Path.home() / ".codex" / "auth.json").exists() or \
            read_path("credentials", "codex.json").exists():
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
                   "voice", "approvals", "security", "posture", "production", "learning", "persona")


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
    from okami.core.platform_compat import secure_chmod
    created = []
    for fname, content in stubs.items():
        p = ws / fname
        if not p.exists():
            p.write_text(content, encoding="utf-8", newline="\n")
            secure_chmod(p, mode=0o600)                # identidade (SOUL/VOICE/PERSONA) é privada do dono
            created.append(fname)
    return created


def _slug(name: str) -> str:
    """Nome → id de agente (kebab, só [a-z0-9-]). 'Okami' → 'okami', 'Time UX' → 'time-ux'."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _ensure_agent(agent_id: str, *, name: str | None = None, provider: str | None = None,
                  memory: str | None = None, match=None, telegram_token: str | None = None,
                  telegram_allow=None, telegram_allow_all: bool = False) -> bool:
    """Cria (ou atualiza) agents/<id>/: agent.yaml + identidade própria. Idempotente.
    Devolve True se acabou de criar. É o que materializa a estrutura multi-agente em disco."""
    import yaml as _yaml

    from okami.home import agents_dir
    d = agents_dir() / agent_id
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
    if telegram_allow:   # lista específica → AUTORITATIVA: não é "todos" (limpa allow_all fantasma)
        tg = spec.setdefault("channels", {}).setdefault("telegram", {})
        tg["allow_chats"] = list(telegram_allow)
        tg.pop("allow_all", None)
    if telegram_allow_all:   # todos → a lista vira irrelevante; remove p/ não confundir (allow_all domina)
        tg = spec.setdefault("channels", {}).setdefault("telegram", {})
        tg["allow_all"] = True
        tg.pop("allow_chats", None)
    d.mkdir(parents=True, exist_ok=True)
    from okami.core.safe_io import write_atomic
    write_atomic(af, _yaml.safe_dump(spec, allow_unicode=True, sort_keys=False) or "{}\n", mode=0o600)
    #                  agent.yaml carrega o telegram_token → 0600 (não world-readable em VPS multi-usuário)
    _write_persona_stubs(d, name or agent_id)
    return not existed


def _resolve_agent(agent: str | None, workspace: str):
    """(cfg, ws_arquivos, nome, casa) de um agente. Sem -a, usa o agente DEFAULT (agents.default do setup).

    SEPARA dois conceitos que antes eram o MESMO diretório (e prendiam o agente na pastinha de config):
      - casa (identidade SOUL/VOICE/PERSONA + memória + sessões): ISOLADA em agents/<id>/ (ou, sem agente,
        workspaces/default). Nunca vai pro projeto do usuário.
      - ws_arquivos (onde o agente LÊ/EDITA): `--workspace` explícito vence; senão o CWD (a pasta onde a
        pessoa rodou o okami). Com open_fs (CLI) o agente ainda alcança caminhos absolutos em todo o FS."""
    def _ws_file() -> Path:
        if workspace and workspace != "workspaces/default":
            return Path(workspace).expanduser()
        return Path.cwd()                          # padrão: trabalha NA pasta onde você rodou o okami

    if not agent:                                  # sem -a → tenta o agente default
        try:                                       # load_config() DIRETO (não `_load()`): checagem muda,
            agent = (load_config().agents or {}).get("default")  # não deve imprimir nem oferecer setup —
        except Exception:  # noqa: BLE001           # isso é papel do fallback abaixo (print/oferta 1x só)
            agent = None
    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não existe[/red] (crie: okami agent new {agent})")
            raise typer.Exit(1)
        graw, _ = load_raw()
        return effective_config(graw, spec), _ws_file(), agent, spec.dir
    # sem agente: casa = workspaces/default (memória isolada na casa global), arquivos = --workspace/CWD
    from okami.home import base_dir
    return _load_or_offer_setup(), _ws_file(), "okami", base_dir() / "workspaces" / "default"


def _write_local(update: dict) -> None:
    """Mescla chaves no okami.local.yaml (override não-destrutivo do okami.yaml) — escrita durável.

    Merge é PROFUNDO (não `.update()` raso): um `update={"providers": {"claude": {"model": "x"}}}`
    preserva outras chaves já gravadas em `providers.claude` (e outros providers) em vez de sobrescrever
    o bloco inteiro. Usado por `okami model <alias> --save` p/ persistir provider+modelo num único write."""
    from okami.config import _deep_merge
    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = config_dir() / "okami.local.yaml"
    data = read_yaml_resilient(p, default={})       # recupera de backup se o atual estiver corrompido
    data = _deep_merge(data, update)
    secure_write_yaml(p, data)                       # atômico + backup rotacionado + .last-good (P1.2)


def _write_model_override(provider_id: str, model: str | None) -> None:
    """Persiste `default_provider` + (se houver modelo resolvido) `providers.<id>.model` em
    okami.local.yaml — override NÃO-destrutivo (okami.yaml continua declarativo/intocado).
    Fonte única usada por `okami model <token> --save` e `/model <token> --save` (gateway)."""
    update: dict = {"default_provider": provider_id}
    if model:
        update["providers"] = {provider_id: {"model": model}}
    _write_local(update)


