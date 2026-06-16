"""`okami lsp` — inspeciona os language servers que o LSP usaria p/ diagnostics semânticos (#17)."""
from __future__ import annotations

import typer
from okami.cli._app import app, console
from okami.i18n import t as _tr

lsp_app = typer.Typer(invoke_without_command=True,
                      help=_tr("cli.lsp", _default="Language servers for semantic diagnostics on write/edit (status/list/which)."))
app.add_typer(lsp_app, name="lsp")


@lsp_app.callback(invoke_without_command=True)
def lsp_main(ctx: typer.Context) -> None:
    """`okami lsp` sem subcomando → status."""
    if ctx.invoked_subcommand is None:
        lsp_status(json_out=False)


@lsp_app.command("status", help=_tr("cli.lsp.status", _default="Show each language server and whether its binary is installed."))
def lsp_status(
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.lsp.status.json", _default="Structured JSON.")),
) -> None:
    """Estado de cada language server (binário instalado?)."""
    from okami.lsp.servers import server_status
    rows = server_status()
    if json_out:
        import json as _json
        console.print_json(_json.dumps(rows, ensure_ascii=False))
        return
    from rich.table import Table
    tbl = Table(title="language servers (diagnostics no write/edit)", title_style="bold")
    for col in ("id", "binário", "instalado", "extensões"):
        tbl.add_column(col)
    for r in rows:
        mark = "[green]✓[/green]" if r["installed"] else "[dim]—[/dim]"
        tbl.add_row(r["id"], r["binary"], mark, " ".join(r["extensions"]))
    console.print(tbl)
    if not any(r["installed"] for r in rows):
        console.print("[dim]nenhum instalado — diagnostics semânticos ficam off; o lint local segue valendo.[/dim]")


@lsp_app.command("list", help=_tr("cli.lsp.list", _default="List supported language servers and how to install each."))
def lsp_list(
    installed_only: bool = typer.Option(False, "--installed-only", help=_tr("cli.lsp.list.inst", _default="Only servers whose binary is present.")),
) -> None:
    """Lista os servidores suportados + a dica de install de cada um."""
    from okami.lsp.servers import LSP_SERVERS, binary_available
    for s in LSP_SERVERS:
        present = binary_available(s)
        if installed_only and not present:
            continue
        mark = "[green]✓[/green]" if present else "[yellow]instalar:[/yellow]"
        hint = "" if present else f" [dim]{s.install_hint}[/dim]"
        console.print(f"{mark} [bold]{s.id}[/bold] ({', '.join(s.extensions)}){hint}")


@lsp_app.command("probe", help=_tr("cli.lsp.probe", _default="Run the language server on a file and print its diagnostics (okami lsp probe <file>)."))
def lsp_probe(
    file: str = typer.Argument(..., help=_tr("cli.lsp.probe.file", _default="File to diagnose (must be inside a git repo).")),
) -> None:
    """Roda o language server (via pool persistente) num arquivo e mostra os diagnostics — prova o stack
    de ponta a ponta. Sem servidor / fora de repo git → mensagem, nunca crasha."""
    from pathlib import Path

    from okami.lsp.pool import LspPool
    from okami.lsp.reporter import report_for_file
    p = Path(file).resolve()
    if not p.is_file():
        console.print(f"[red]arquivo não encontrado:[/red] {file}")
        raise typer.Exit(1)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        console.print(f"[red]não consegui ler:[/red] {e}")
        raise typer.Exit(1) from e
    pool = LspPool()
    try:
        diags = pool.diagnose_path(p.parent, p.name, text)
    finally:
        pool.shutdown()
    if not diags:
        console.print("[dim]sem diagnostics (ou servidor ausente / arquivo fora de repo git). "
                      "Veja `okami lsp status`.[/dim]")
        return
    block = report_for_file(str(p), diags, severities=frozenset({1, 2, 3, 4}))
    console.print(block or "[dim]sem erros.[/dim]")


@lsp_app.command("which", help=_tr("cli.lsp.which", _default="Print the resolved binary path for a language server (okami lsp which <id>)."))
def lsp_which(
    server_id: str = typer.Argument(..., help=_tr("cli.lsp.which.id", _default="Server id (see `okami lsp list`).")),
) -> None:
    """Caminho resolvido do binário de um servidor (ou erro se desconhecido/ausente)."""
    import shutil

    from okami.lsp.servers import server_by_id
    s = server_by_id(server_id)
    if s is None:
        console.print(f"[red]servidor desconhecido:[/red] {server_id} [dim](veja `okami lsp list`)[/dim]")
        raise typer.Exit(1)
    path = shutil.which(s.binary)
    if not path:                                          # conhecido mas não instalado → informa (exit 0)
        console.print(f"[yellow]{s.id}: binário '{s.binary}' não está no PATH[/yellow] [dim]→ {s.install_hint}[/dim]")
        return
    console.print(f"{s.id}: {path}")
