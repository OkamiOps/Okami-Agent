"""Diagnóstico de tamanho de prompt: `okami prompt-size` (WIN4, espírito hermes_cli/prompt_size.py).

Monta o MESMO system prompt que o harness mandaria pro provider configurado (ou `--provider`) e mostra
o breakdown por SEÇÃO (tools, estilo, orientação de workspace, memória/core) em chars/tokens — sem
chamar rede nenhuma (não faz completion, só monta texto local). Ajuda a achar onde o orçamento fixo do
prompt está indo, sobretudo em modelo local/fraco de janela pequena.
"""
from __future__ import annotations

import typer
from okami.i18n import t as _tr

from okami.cli._app import app, console


@app.command("prompt-size", help=_tr("cli.prompt_size", _default="Diagnóstico: breakdown do system prompt (tools/estilo/memória) em chars/tokens, por seção."))
def prompt_size(
    agent: str = typer.Option("", "-a", "--agent", help=_tr("cli.prompt_size.agent", _default="Agente cuja identidade/memória medir (default: agente configurado).")),
    workspace: str = typer.Option(".", "-w", "--workspace", help=_tr("cli.prompt_size.workspace", _default="Workspace de arquivos (orientação do prompt).")),
    provider: str = typer.Option("", "-p", "--provider", help=_tr("cli.prompt_size.provider", _default="Provider a medir (default: o default_provider do okami.yaml).")),
    surface: str = typer.Option("cli", "--surface", help=_tr("cli.prompt_size.surface", _default="Superfície (cli/telegram/...) — muda o platform_hint de estilo.")),
    native: bool = typer.Option(False, "--native", help=_tr("cli.prompt_size.native", _default="Mede o ramo NATIVO (function-calling) em vez do ramo JSON-em-texto (default).")),
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.prompt_size.json", _default="Saída estruturada (scripts/CI).")),
) -> None:
    """Breakdown do system prompt por seção (chars/tokens) — não chama nenhum provider, só monta texto."""
    from okami.cli._shared import _resolve_agent
    from okami.core import Task, default_registry
    from okami.core.harness.prompt import prompt_size_sections
    from okami.core.tool_policy import filter_registry
    from okami.memory import files as memfiles

    cfg, ws, _who, home = _resolve_agent(agent or None, workspace)
    try:
        pc = cfg.provider(provider or None)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    registry = filter_registry(default_registry(), surface, config=getattr(cfg, "tools", None))
    core_block = memfiles.core_block(home, (cfg.memory or {}).get("files", {}))
    task = Task(goal="(diagnóstico de tamanho de prompt — nenhuma tarefa real)", exit_criteria=[])

    data = prompt_size_sections(task, registry, core_block, workspace=ws, surface=surface,
                                model=pc.model, allow_paths=None, open_fs=False, native=native)

    if json_out:
        import json as _json
        console.print_json(_json.dumps(data, ensure_ascii=False))
        return

    from okami.cli import _ui
    console.print()
    console.print(_ui.header("prompt-size", f"{data['model']} · {data['platform']}"
                             f" · {'nativo' if data['native'] else 'json'} · {data['tool_count']} tools"))
    console.print()
    t = _ui.data_table(("seção", {"style": f"bold {_ui.FG}", "no_wrap": True}),
                       ("chars", {"justify": "right", "style": _ui.SOFT}),
                       ("tokens (~)", {"justify": "right", "style": _ui.MAGENTA}))
    for s in data["sections"]:
        t.add_row(s["label"], f"{s['chars']:,}", f"{s['tokens']:,}")
    console.print(t)
    console.print()
    total = data["total"]
    console.print(_ui.fields([("TOTAL", f"{total['chars']:,} chars  ·  ~{total['tokens']:,} tokens")], label_w=8))
    console.print()
