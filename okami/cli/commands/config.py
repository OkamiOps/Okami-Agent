"""Configuração efetiva: config show/get/set/unset/path/edit/check."""
from __future__ import annotations

import json
import re

import typer
from okami.config import config_dir
from okami.i18n import t as _tr
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _set_env_var,
)


def _is_secret_key(key: str) -> bool:
    """Chave estilo env-var (MAIÚSCULAS, sem ponto) → segredo → vai pro .env. Ex.: OPENAI_API_KEY."""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", key))


_SENSITIVE_SEG = re.compile(
    r"api[_-]?keys?|tokens?|authorization|passwo?rds?|secrets?|credentials?|private[_-]?keys?|apikey",
    re.IGNORECASE,
)


def _is_sensitive_dotted(key: str) -> bool:
    """Chave PONTILHADA que aponta p/ segredo (#6): providers.openai.api_key, channels.telegram.token,
    mcp.servers.x.headers.Authorization, memory.honcho.api_key… — NÃO pode ir em texto no YAML versionável."""
    return any(_SENSITIVE_SEG.search(seg) for seg in key.split("."))


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


def _switch_provider_model() -> None:
    """Dispara o MESMO fluxo interativo do `okami model` (sem args) — troca de provider/modelo por
    alias, com persistência em okami.local.yaml via _write_model_override. Reusa okami/cli/commands/
    model.py (não duplica a lógica de resolução/gravação, que mora em okami/llm/model_aliases.py).

    Sem TTY: degrada mostrando o efetivo atual + dica de comando, igual aos outros ramos do menu."""
    from okami import menu
    from okami.cli.commands.model import _effective, model_cmd

    cfg = _load()
    if not menu._interactive():
        pid, model, source = _effective(cfg)
        console.print(f"🧠 [bold]{pid}[/bold] · {model}  [dim]({source})[/dim]")
        console.print(_ui_hint("sem TTY — use: okami model <alias> (ex.: okami model sonnet)"))
        return
    model_cmd(token=None, save=True, as_json=False)


def _ui_hint(msg: str) -> str:
    from okami.cli import _ui
    return _ui.hint(msg)


def _provider_auth_state(cfg, pid: str):
    """Como o provider `pid` autentica e se JÁ está autenticado. Retorna (metodo, key_env, ok):
    - metodo: 'oauth' (device-flow/CLI: codex/claude/...) | 'api_key' (cola a chave no .env: minimax/mimo/grok/…)
    - key_env: nome da env var da chave (só p/ api_key)
    - ok: bool — já autenticado (token presente / env var setada)."""
    import os
    from okami.llm import oauth
    pc = cfg.provider(pid)
    auth = (getattr(pc, "auth", "") or "").lower()
    key_env = getattr(pc, "api_key_env", None) or getattr(pc, "key_env", None)
    if pid == "codex" or getattr(pc, "login_cmd", None) or getattr(pc, "oauth", None) or "oauth" in auth or "subscription" in auth:
        try:
            ok = oauth.codex_logged_in() if pid == "codex" else bool(oauth.load_tokens(pid))
        except Exception:  # noqa: BLE001
            ok = False
        return "oauth", None, ok
    if key_env:            # api_key / token-plan (minimax/mimo/grok/…): a chave mora no .env
        val = os.environ.get(key_env) or ""
        if not val:        # também confere o .env resolvido pela config
            try:
                val = str(getattr(pc, "api_key", "") or "")
            except Exception:  # noqa: BLE001
                val = ""
        return "api_key", key_env, bool(val and val not in ("", "lm-studio"))
    return "none", None, True     # provider sem credencial (ex.: lmstudio local)


def _authenticate_provider() -> None:
    """`autenticar provider` — abre TODOS os providers que precisam de credencial (assinatura/OAuth E
    token-plan/API-key) e autentica o escolhido no método certo: device-flow/CLI (codex/claude…) OU
    colar a Subscription Key no .env (minimax/mimo/grok…). É o que o dono pediu: abrir os providers e
    autenticar, sem editar arquivo. Reusa login()/config_set — não duplica auth.

    Sem TTY: lista os providers + status + a dica de comando (degrada, não trava)."""
    from okami import menu
    from okami.cli.commands.basics import login

    cfg = _load()
    rows = []      # (pid, metodo, key_env, ok)
    for pid in (cfg.providers or {}):
        method, key_env, ok = _provider_auth_state(cfg, pid)
        if method == "none":
            continue                          # local/sem credencial não aparece no menu de auth
        rows.append((pid, method, key_env, ok))
    if not rows:
        console.print(_ui_hint("nenhum provider que exija login — adicione com `okami provider add`."))
        return

    def _label(pid, method, ok):
        badge = "● autenticado" if ok else "○ falta autenticar"
        how = "OAuth/device" if method == "oauth" else "API key (.env)"
        return f"{pid} — {badge} · {how}"

    if not menu._interactive():
        for pid, method, key_env, ok in rows:
            console.print(f"  {_label(pid, method, ok)}")
        console.print(_ui_hint("sem TTY — OAuth: okami login <id> · API key: okami config set <KEY_ENV> <valor>"))
        return
    choice = menu.select("Autenticar qual provider?",
                         [(pid, _label(pid, method, ok), "") for pid, method, key_env, ok in rows])
    if not choice:
        return
    method, key_env, _ok = _provider_auth_state(cfg, choice)
    if method == "oauth":
        login(choice)                         # device-flow / CLI-delegado de verdade (basics.py)
    elif method == "api_key" and key_env:     # token-plan: cola a chave → vai pro .env (config_set)
        console.print(_ui_hint(f"{choice}: cole a Subscription Key / API key (fica só no .env, mascarada)."))
        val = menu.text(f"{key_env}", password=True)
        if val and val.strip():
            config_set(key_env, val.strip())
            console.print(f"🔐 [green]{choice} autenticado[/] — {key_env} salvo no .env.")
        else:
            console.print(_ui_hint("nada colado — cancelado."))


def _show_providers() -> None:
    """`ver providers configurados` — reusa o `okami providers` (basics.py), sem duplicar a listagem."""
    from okami.cli.commands.basics import list_providers
    list_providers(json_out=False)


config_app = typer.Typer(invoke_without_command=True,
                         help=_tr("cli.config", _default="Config (hermes/openclaw-style): show/get/set/edit/path/check. "
                                  "No subcommand opens the interactive panel. Secrets→.env, rest→okami.local.yaml."))
app.add_typer(config_app, name="config")


def _config_effective_yaml() -> str:
    """YAML da config efetiva (base + overrides) com segredos mascarados."""
    import yaml as _yaml
    from okami.config import load_raw
    raw, _ = load_raw()
    return _yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False)


def _config_file_rows():
    from okami.config import global_env_path
    from okami.home import base_dir, okami_home
    return [("casa", okami_home()), ("dados (base)", base_dir()),
            ("base", config_dir() / "okami.yaml"), ("overrides", config_dir() / "okami.local.yaml"),
            (".env projeto", Path(".env")), (".env global", global_env_path()),
            ("policy", Path("okami.policy.yaml"))]


def _files_card():
    from rich.text import Text

    from okami.cli import _ui
    rows = []
    for lbl, p in _config_file_rows():
        ex = p.exists()
        loc = str(p if p.is_absolute() else p.resolve())
        v = Text()
        v.append_text(_ui.dot("ok" if ex else "off"))
        v.append(f"  {loc}", style=_ui.SOFT if ex else _ui.MUTE)
        rows.append((lbl, v))
    return _ui.card(_ui.kv(rows), title="arquivos", subtitle="segredo só no .env (gitignored)")


def _files_fields():
    """Mesmos arquivos do _files_card, mas no estilo `◆ fields` (flat, sem caixa) p/ a visão nova."""
    from rich.text import Text

    from okami.cli import _ui
    rows = []
    for lbl, p in _config_file_rows():
        ex = p.exists()
        loc = str(p if p.is_absolute() else p.resolve())
        v = Text()
        v.append_text(_ui.dot("ok" if ex else "off"))
        v.append(f"  {loc}", style=_ui.SOFT if ex else _ui.MUTE)
        rows.append((lbl, v))
    return _ui.fields(rows, label_w=14)


def _summary_fields():
    """`◆ Resumo`: os valores RESOLVIDOS que mais importam (provider/memória/aprovação/sandbox/canais)."""
    from rich.text import Text

    from okami.cli import _ui
    try:
        cfg = _load()
    except Exception:  # noqa: BLE001
        return Text("  config não carrega — okami config check", style=_ui.AMBER)
    pc = cfg.provider()
    prov_v = Text()
    prov_v.append(cfg.default_provider, style=f"bold {_ui.FG}")
    prov_v.append(f" · {pc.model} · {pc.tier}   ", style=_ui.SOFT)
    prov_v.append_text(_ui.badge("ready", "pronto") if pc.ready else _ui.badge("missing", "falta auth"))
    appr = (cfg.approvals or {}).get("mode", "manual")
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(cfg.sandbox or {})
    sb_v = Text(f"{sb.backend} · {sb.mode} · net {'on' if sb.network_on else 'off'}", style=_ui.SOFT)
    nchan = len(cfg.gateway or {})
    return _ui.fields([
        ("provider", prov_v),
        ("memória", Text((cfg.memory or {}).get("backend", "sqlite-fts5"), style=_ui.FG)),
        ("aprovação", _ui.badge("ok" if appr in ("manual", "smart") else "warn", appr)),
        ("sandbox", sb_v),
        ("canais", Text(f"{nchan} no gateway" if nchan else "nenhum — DM local (okami chat)",
                        style=_ui.SOFT if nchan else _ui.MUTE)),
    ], label_w=14)


def _render_config_view(diff: bool = False) -> None:
    from rich.syntax import Syntax

    from okami import __version__
    from okami.cli import _ui
    console.print()
    console.print(_ui.masthead(__version__, right="config efetiva"))
    console.print()
    # grade: Arquivos | Resumo (lado a lado em terminal largo; empilha no estreito)
    console.print(_ui.grid([
        _ui.panel(_files_fields(), title="Arquivos", accent=_ui.CYAN, subtitle="segredo só no .env"),
        _ui.panel(_summary_fields(), title="Resumo", accent=_ui.ORANGE),
    ], width=console.width))
    # YAML efetivo (ou overrides) em card largo
    if diff:
        p = config_dir() / "okami.local.yaml"
        if not p.exists():
            console.print(_ui.panel(_ui.hint("sem overrides — okami.local.yaml não existe"),
                                    title="Overrides", accent=_ui.MAGENTA))
        else:
            body = Syntax(p.read_text(encoding="utf-8"), "yaml", theme="ansi_dark", background_color="default")
            console.print(_ui.panel(body, title="Overrides", subtitle="okami.local.yaml", accent=_ui.MAGENTA))
    else:
        body = Syntax(_config_effective_yaml(), "yaml", theme="ansi_dark", background_color="default")
        console.print(_ui.panel(body, title="Efetiva", subtitle="okami.yaml + overrides · segredos mascarados",
                                accent=_ui.MAGENTA))
    console.print(_ui.footer("Próximos passos:", [
        ("okami config set <k> <v>", "segredo→.env · resto→okami.local.yaml"),
        ("okami config get <k>", "lê um valor resolvido"),
        ("okami config check", "valida que a config carrega (lite doctor)"),
    ]))
    console.print()


@config_app.callback(invoke_without_command=True,
                     help=_tr("cli.config.main", _default="`okami config` with no subcommand: show the effective config and open a menu."))
def config_main(ctx: typer.Context) -> None:
    """`okami config` SEM subcomando: mostra a config efetiva e abre um menu (não exige argumentos).

    Era o que faltava — antes `okami config` pedia subcomando. Agora, igual hermes/openclaw, você dá
    `config` e cai num painel: ver / mudar / ler / editar / paths / validar."""
    if ctx.invoked_subcommand is not None:
        return
    from okami.cli import _ui
    try:
        _render_config_view()
    except FileNotFoundError:                          # sem okami.yaml (fresh/antes do setup): degrada limpo
        console.print()
        console.print(_ui.panel(
            _ui.hint("nenhum okami.yaml encontrado nesta pasta nem em ~/.okami.\n"
                     "Rode [bold]okami setup[/] para criar a config, ou entre num projeto que já tenha um."),
            title="config", accent=_ui.ORANGE))
        console.print()
        raise typer.Exit(1)
    from okami import menu
    if not menu._interactive():                       # script/pipe: só mostra (não trava pedindo input)
        console.print(_ui.hint("show · get <k> · set <k> <v> · edit · path · check · okami model <alias>"))
        return
    while True:
        pick = menu.select("config — o que fazer?", [
            ("provider", "trocar provider/modelo (picker)", ""),
            ("autenticar", "autenticar provider (login assinatura/OAuth)", ""),
            ("providers", "ver providers configurados", ""),
            ("set", "mudar um valor (segredo→.env, resto→local)", ""),
            ("get", "ler um valor", ""),
            ("edit", "abrir no editor ($EDITOR)", ""),
            ("show", "rever a config efetiva", ""),
            ("check", "validar (lite doctor)", ""),
            ("sair", "fechar o painel", ""),
        ], default="set")
        if pick in (None, "sair"):
            return
        if pick == "provider":
            _switch_provider_model()
        elif pick == "autenticar":
            _authenticate_provider()
        elif pick == "providers":
            _show_providers()
        elif pick == "set":
            key = menu.text("chave (ex.: memory.backend ou OPENAI_API_KEY)").strip()
            if not key:
                continue
            val = menu.text(f"valor de {key}", password=_is_secret_key(key))
            config_set(key, val)
        elif pick == "get":
            key = menu.text("chave a ler (ex.: default_provider)").strip()
            if key:
                config_get(key)
        elif pick == "edit":
            config_edit(base=False)
        elif pick == "show":
            console.print(_config_effective_yaml())
        elif pick == "check":
            try:
                config_check()
            except typer.Exit:
                pass


@config_app.command("show", help=_tr("cli.config.show", _default="Show the effective config (okami.yaml + overrides), with secrets masked."))
def config_show(diff: bool = typer.Option(False, "--diff", help=_tr("cli.config.show.diff", _default="Only the overrides (okami.local.yaml)."))) -> None:
    """Mostra a config efetiva (okami.yaml + overrides), com segredos mascarados."""
    if console.is_terminal:                           # TTY → visão bonita (cards + arquivos)
        _render_config_view(diff=diff)
        return
    import yaml as _yaml                               # pipe/script → YAML cru (greppável), segredos mascarados
    if diff:
        p = config_dir() / "okami.local.yaml"
        console.print(p.read_text(encoding="utf-8") if p.exists() else "(sem overrides)")
        return
    from okami.config import load_raw
    raw, _ = load_raw()
    console.print(_yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False))


def _looks_secret_value(val) -> bool:
    """True se o VALOR escalar parece um segredo (sk-…, token JWT, etc.) mesmo com chave inócua."""
    from okami.core.redact import redact
    s = str(val)
    return bool(s) and redact(s) != s          # o redator central mexeu → tem padrão de segredo


@config_app.command("get", help=_tr("cli.config.get", _default="Read a value from the effective config (dotted key). Secrets masked by default."))
def config_get(
    key: str = typer.Argument(..., help=_tr("cli.config.get.key", _default="Dotted key, e.g. memory.backend")),
    raw_out: bool = typer.Option(False, "--raw", help=_tr("cli.config.get.raw", _default="Show the RAW value even if it is a secret (careful: leaks).")),
) -> None:
    """Lê um valor da config efetiva (chave pontilhada). Segredo é mascarado por padrão (#9; use --raw p/ ver)."""
    import yaml as _yaml
    from okami.config import load_raw
    raw, _ = load_raw()
    val = _dotted_get(raw, key)
    if val is None:
        console.print("[dim](não definido)[/dim]")
    elif isinstance(val, (dict, list)):
        console.print(_yaml.safe_dump(_redact(val) if not raw_out else val, allow_unicode=True, sort_keys=False))
    elif not raw_out and (_is_sensitive_dotted(key) or _looks_secret_value(val)):
        # #2/#9: scalar sensível NÃO sai cru — antes `config get channels.telegram.token` cuspia o token.
        console.print("[yellow]***[/] [dim](segredo — use --raw p/ ver o valor cru)[/dim]")
    else:
        console.print(str(val))


@config_app.command("set", help=_tr("cli.config.set", _default="Set a value — auto-routes: secret (UPPERCASE) → .env, rest → okami.local.yaml."))
def config_set(
    key: str = typer.Argument(..., help=_tr("cli.config.set.key", _default="Dotted key (e.g. memory.backend) or env (e.g. OPENAI_API_KEY).")),
    value: str = typer.Argument(..., help=_tr("cli.config.set.value", _default="Value (true/false/number/list a,b/json too).")),
    project: bool = typer.Option(False, "--project", help=_tr("cli.config.set.project", _default="Secret in the PROJECT .env (default = global $OKAMI_HOME/.env, ~/.okami).")),
) -> None:
    """Define um valor — auto-roteia: segredo (MAIÚSCULAS) → .env, resto → okami.local.yaml.

    Segredo vai pro .env GLOBAL ($OKAMI_HOME/.env, default ~/.okami/.env) por padrão → vale em QUALQUER workspace
    (ex.: ELEVENLABS_API_KEY). Use --project p/ gravar só no projeto atual."""
    import yaml as _yaml
    if _is_secret_key(key):
        from okami.config import global_env_path
        _set_env_var(key, value, path=".env" if project else None)
        where = "projeto (.env)" if project else f"global ({global_env_path()})"
        console.print(f"[green]🔑 {key} →[/green] {where} [dim](0600, não versionado)[/dim]")
        return
    if _is_sensitive_dotted(key) and not str(value).strip().startswith("${"):   # #6: segredo NÃO vai em texto
        env_name = key.replace(".", "_").upper()
        console.print(f"[red]✗ '{key}' parece SEGREDO[/red] — não gravo em texto no okami.local.yaml (versionável).")
        console.print(f"[dim]→ guarde como env var:[/dim] [bold]okami config set {env_name} <valor>[/bold]")
        console.print(f"[dim]  e referencie no yaml com:[/dim] [bold]okami config set {key} '${{{env_name}}}'[/bold]")
        raise typer.Exit(2)
    p = config_dir() / "okami.local.yaml"
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    coerced = _coerce(value)
    _dotted_set(data, key, coerced)
    from okami.core.safe_io import secure_write_yaml
    secure_write_yaml(p, data)              # atômico + backup + .last-good (P1.2)
    console.print(f"[green]✓ {key}[/green] = {coerced!r} [dim]→ okami.local.yaml[/dim]")


@config_app.command("unset", help=_tr("cli.config.unset", _default="Remove an override (okami.local.yaml). Does not touch the base okami.yaml."))
def config_unset(key: str = typer.Argument(..., help=_tr("cli.config.unset.key", _default="Dotted key to remove from the override."))) -> None:
    """Remove um override (okami.local.yaml). Não toca no okami.yaml base."""
    import yaml as _yaml
    p = config_dir() / "okami.local.yaml"
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    if _dotted_del(data, key):
        from okami.core.safe_io import secure_write_yaml
        secure_write_yaml(p, data)         # atômico + backup + .last-good (P1.2)
        console.print(f"[green]✓ removido:[/green] {key}")
    else:
        console.print(f"[yellow]não estava nos overrides:[/yellow] {key}")


@config_app.command("path", help=_tr("cli.config.path", _default="Show where the config files live (incl. the GLOBAL secrets .env)."))
def config_path() -> None:
    """Mostra onde ficam os arquivos de config (incl. o .env GLOBAL de segredos)."""
    console.print(_files_card())


@config_app.command("edit", help=_tr("cli.config.edit", _default="Open the config in your editor ($EDITOR, else notepad/nano)."))
def config_edit(base: bool = typer.Option(False, "--base", help=_tr("cli.config.edit.base", _default="Open okami.yaml instead of the override."))) -> None:
    """Abre a config no seu editor ($EDITOR, senão notepad/nano)."""
    import os
    import subprocess
    target = config_dir() / ("okami.yaml" if base else "okami.local.yaml")
    if not target.exists():
        target.write_text("# overrides locais do Okami (mescla sobre o okami.yaml)\n", encoding="utf-8")
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    subprocess.call([editor, str(target)])


@config_app.command("check", help=_tr("cli.config.check", _default="Validate that the config loads and point out what's missing (lite doctor)."))
def config_check(
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.config.check.json", _default="JSON output (for script/CI) — like doctor/policy.")),
) -> None:
    """Valida que a config carrega e aponta o que falta (lite doctor)."""
    import json as _json
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        if json_out:
            console.print_json(_json.dumps({"ok": False, "config_loads": False, "error": str(e)}, ensure_ascii=False))
        else:
            console.print(f"[red]✗ config inválida:[/red] {e}")
        raise typer.Exit(1)
    pc = cfg.provider()
    if json_out:
        console.print_json(_json.dumps({"ok": bool(pc.ready), "config_loads": True,
                                        "default_provider": cfg.default_provider, "model": pc.model,
                                        "ready": bool(pc.ready)}, ensure_ascii=False))
        raise typer.Exit(0 if pc.ready else 2)
    console.print("[green]✓ config carrega[/green]")
    s = "[green]pronto[/green]" if pc.ready else "[yellow]falta auth/chave[/yellow]"
    console.print(f"  default_provider: [bold]{cfg.default_provider}[/bold] ({pc.model}) — {s}")
    if not pc.ready:
        console.print(f"  [dim]→ okami login {cfg.default_provider}  (ou okami provider models {cfg.default_provider})[/dim]")
        raise typer.Exit(2)


