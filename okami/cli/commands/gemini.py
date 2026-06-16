"""`okami gemini` — login no tier GRÁTIS de Gemini via Google Code Assist (cloudcode-pa) + quota (#17).

Login OAuth PKCE com a conta Google: o token vai p/ ~/.okami/auth/google_oauth.json (0600). Depois é só
apontar um provider com `transport: gemini_cloudcode`. Sem credencial, os comandos degradam com graça.
"""
from __future__ import annotations

import secrets

import typer
from okami.cli._app import app, console
from okami.i18n import t as _tr

gemini_app = typer.Typer(invoke_without_command=True,
                         help=_tr("cli.gemini", _default="Google Code Assist: free Gemini tier via OAuth (login/status/quota)."))
app.add_typer(gemini_app, name="gemini")

_REDIRECT = "http://127.0.0.1:8085/oauth2callback"


def _auth_path():
    from okami.home import okami_home
    return okami_home() / "auth" / "google_oauth.json"


@gemini_app.callback(invoke_without_command=True)
def gemini_main(ctx: typer.Context) -> None:
    """`okami gemini` sem subcomando → status."""
    if ctx.invoked_subcommand is None:
        gemini_status()


@gemini_app.command("login", help=_tr("cli.gemini.login", _default="Log in to the free Gemini tier (Google Code Assist) via OAuth."))
def gemini_login(
    print_url: bool = typer.Option(False, "--print-url", help=_tr("cli.gemini.login.url", _default="Just print the authorization URL (don't open a browser).")),
) -> None:
    """Inicia o OAuth PKCE: imprime a URL de autorização (ou abre o browser). Troca de code → token é o
    próximo passo (precisa do callback local); aqui montamos a URL real com PKCE."""
    from okami.llm.code_assist import DEFAULT_CLIENT_ID, build_auth_url, generate_pkce_pair
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_auth_url(client_id=DEFAULT_CLIENT_ID, redirect_uri=_REDIRECT, state=state, challenge=challenge)
    if print_url:
        typer.echo(url)                                   # cru (sem wrap do rich) → URL colável/scriptável
        return
    _run_login_flow(url, verifier, state)


def _run_login_flow(url: str, verifier: str, state: str, *, timeout: float = 180.0) -> None:
    """Sobe o callback local, abre o browser, recebe o code, troca por token e persiste (0600)."""
    import threading
    import time
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from okami.llm.code_assist import exchange_code, save_credentials
    holder: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            if (q.get("state") or [""])[0] == state:      # CSRF: só aceita o state que emitimos
                holder["code"] = (q.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Okami: autorizado — pode fechar esta aba.".encode("utf-8"))

        def log_message(self, *a):                        # silêncio
            return

    try:
        httpd = HTTPServer(("127.0.0.1", 8085), _Handler)
    except OSError as e:
        console.print(f"[red]não consegui abrir o callback em 127.0.0.1:8085 ({e})[/red] — "
                      "feche o que está usando a porta e tente de novo.")
        raise typer.Exit(1) from e
    threading.Thread(target=httpd.handle_request, daemon=True).start()
    console.print("[bold]Login no tier grátis de Gemini (Google Code Assist)[/bold]")
    console.print(f"abrindo o navegador… se não abrir, cole esta URL:\n[cyan]{url}[/cyan]\n")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 — headless: o usuário cola a URL manualmente
        pass
    deadline = time.monotonic() + timeout
    while "code" not in holder and time.monotonic() < deadline:
        time.sleep(0.2)
    httpd.server_close()
    if not holder.get("code"):
        console.print("[yellow]login não completou (timeout/sem code).[/yellow] Tente de novo.")
        raise typer.Exit(1)
    try:
        tok = exchange_code(holder["code"], verifier, redirect_uri=_REDIRECT)
    except Exception as e:  # noqa: BLE001
        from okami.core.redact import redact
        console.print(f"[red]troca de token falhou:[/red] {redact(str(e))[:200]}")
        raise typer.Exit(1) from e
    import time as _t
    creds = dict(tok)
    creds["expires_at"] = _t.time() + float(tok.get("expires_in") or 3600)
    save_credentials(creds)
    console.print(f"[green]✓ logado[/green] [dim]credencial em {_auth_path()} (0600). "
                  "Aponte um provider com transport: gemini_cloudcode.[/dim]")


@gemini_app.command("status", help=_tr("cli.gemini.status", _default="Show whether a Google Code Assist credential is present."))
def gemini_status() -> None:
    """Mostra se há credencial Google em disco (sem revelar o token)."""
    p = _auth_path()
    if p.exists():
        console.print(f"[green]✓ credencial Google presente[/green] [dim]{p}[/dim]")
    else:
        console.print("[yellow]sem credencial Google[/yellow] [dim]— rode `okami gemini login`.[/dim]")


@gemini_app.command("quota", help=_tr("cli.gemini.quota", _default="Show remaining daily quota per Gemini model (needs a credential)."))
def gemini_quota() -> None:
    """Quota diária restante por modelo (precisa de credencial; degrada com graça)."""
    p = _auth_path()
    if not p.exists():
        console.print("[yellow]sem credencial Google[/yellow] [dim]— rode `okami gemini login` primeiro.[/dim]")
        raise typer.Exit(1)
    console.print("[dim]consulta de quota ao vivo precisa do token — use após o login (retrieveUserQuota).[/dim]")
