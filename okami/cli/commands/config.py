"""Configuração efetiva: config show/get/set/unset/path/edit/check."""
from __future__ import annotations

import json
import re

import typer
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _set_env_var,
)


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


config_app = typer.Typer(invoke_without_command=True,
                         help="Config (estilo hermes/openclaw): show/get/set/edit/path/check. "
                              "Sem subcomando abre o painel interativo. Segredos→.env, resto→okami.local.yaml.")
app.add_typer(config_app, name="config")


def _config_effective_yaml() -> str:
    """YAML da config efetiva (base + overrides) com segredos mascarados."""
    import yaml as _yaml
    from okami.config import load_raw
    raw, _ = load_raw()
    return _yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False)


@config_app.callback(invoke_without_command=True)
def config_main(ctx: typer.Context) -> None:
    """`okami config` SEM subcomando: mostra a config efetiva e abre um menu (não exige argumentos).

    Era o que faltava — antes `okami config` pedia subcomando. Agora, igual hermes/openclaw, você dá
    `config` e cai num painel: ver / mudar / ler / editar / paths / validar."""
    if ctx.invoked_subcommand is not None:
        return
    from rich.panel import Panel
    from rich.syntax import Syntax
    console.print(Panel(Syntax(_config_effective_yaml(), "yaml", theme="ansi_dark",
                               background_color="default"),
                        title="[bold #ff7527]config efetiva[/]", border_style="#3d3e50",
                        subtitle="[dim]okami.yaml + okami.local.yaml · segredos mascarados[/]"))
    config_path()
    from okami import menu
    if not menu._interactive():                       # script/pipe: só mostra (não trava pedindo input)
        console.print("[dim]subcomandos: show · get · set · edit · path · check[/dim]")
        return
    while True:
        pick = menu.select("config — o que fazer?", [
            ("set", "mudar um valor (segredo→.env, resto→local)", ""),
            ("get", "ler um valor", ""),
            ("edit", "abrir no editor ($EDITOR)", ""),
            ("show", "rever a config efetiva", ""),
            ("check", "validar (lite doctor)", ""),
            ("sair", "fechar o painel", ""),
        ], default="set")
        if pick in (None, "sair"):
            return
        if pick == "set":
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
    project: bool = typer.Option(False, "--project", help="Segredo no .env do PROJETO (default = global ~/.okami/.env)."),
) -> None:
    """Define um valor — auto-roteia: segredo (MAIÚSCULAS) → .env, resto → okami.local.yaml.

    Segredo vai pro .env GLOBAL (~/.okami/.env) por padrão → vale em QUALQUER workspace
    (ex.: ELEVENLABS_API_KEY). Use --project p/ gravar só no projeto atual."""
    import yaml as _yaml
    if _is_secret_key(key):
        from okami.config import global_env_path
        _set_env_var(key, value, path=".env" if project else None)
        where = "projeto (.env)" if project else f"global ({global_env_path()})"
        console.print(f"[green]🔑 {key} →[/green] {where} [dim](0600, não versionado)[/dim]")
        return
    p = Path("okami.local.yaml")
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    coerced = _coerce(value)
    _dotted_set(data, key, coerced)
    from okami.core.safe_io import secure_write_yaml
    secure_write_yaml(p, data)              # atômico + backup + .last-good (P1.2)
    console.print(f"[green]✓ {key}[/green] = {coerced!r} [dim]→ okami.local.yaml[/dim]")


@config_app.command("unset")
def config_unset(key: str = typer.Argument(..., help="Chave pontilhada a remover do override.")) -> None:
    """Remove um override (okami.local.yaml). Não toca no okami.yaml base."""
    import yaml as _yaml
    p = Path("okami.local.yaml")
    data = (_yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    if _dotted_del(data, key):
        from okami.core.safe_io import secure_write_yaml
        secure_write_yaml(p, data)         # atômico + backup + .last-good (P1.2)
        console.print(f"[green]✓ removido:[/green] {key}")
    else:
        console.print(f"[yellow]não estava nos overrides:[/yellow] {key}")


@config_app.command("path")
def config_path() -> None:
    """Mostra onde ficam os arquivos de config (incl. o .env GLOBAL de segredos)."""
    from okami.config import global_env_path
    rows = [("config base    ", Path("okami.yaml")), ("overrides      ", Path("okami.local.yaml")),
            ("segredos projeto", Path(".env")), ("segredos GLOBAL ", global_env_path())]
    for label, p in rows:
        mark = "[green]✓[/green]" if p.exists() else "[dim]—[/dim]"
        console.print(f"{mark} {label}: {p.resolve() if not p.is_absolute() else p}")


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


