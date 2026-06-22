"""Tools de ambiente remoto — o agente "entra" num host (SSH/Tailscale) e suas tools de arquivo/shell
passam a operar LÁ.

remote_connect resolve um alias (de `remote.hosts`) ou um host cru, aplicando a allowlist por
superfície (livre no terminal; só alias no Telegram/etc.), faz um health-check antes de assumir, e
persiste o alvo na sessão (sobrevive aos turnos). remote_disconnect volta ao local. A segurança do
run_shell (hardline/jail/aprovação) continua valendo nos comandos remotos — ver okami/core/tools/files.py.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult

def _is_terminal(ctx) -> bool:
    """'Dono presente' (host cru liberado) = open_fs. É FAIL-SAFE: open_fs só é True no `okami chat`
    interativo (chat.py); gateway/Telegram, jobs do scheduler/cron e subagentes têm open_fs=False →
    NÃO-terminal → allowlist obrigatória. (Não usar `surface`: ele defaulta p/ 'cli' e um executor
    autônomo que esqueça de passar surface viraria 'terminal' = bypass da allowlist — achado #1/#11.)"""
    return bool(getattr(ctx, "open_fs", False))


def _remote_cfg(ctx) -> dict:
    cfg = getattr(ctx, "cfg", None)
    rc = getattr(cfg, "remote", None)
    return rc if isinstance(rc, dict) else {}


class RemoteAdd(Tool):
    name = "remote_add"
    description = (
        "Cadastra um host SSH/Tailscale nos remotes (persiste em okami.local.yaml) pra você conectar depois "
        "pelo ALIAS com remote_connect — inclusive no Telegram (a allowlist passa a liberar esse alias). Use "
        "quando o dono te der uma máquina nova pra gerenciar. Valida o host (anti-injeção)."
    )
    args_schema = {
        "alias": "nome curto do host (ex.: prod, vps2)",
        "host": "user@host (ssh) ou nome do nó (tailscale)",
        "via": "(opc) ssh | tailscale (default: ssh se tem '@', senão tailscale)",
    }
    required = ("alias", "host")

    def run(self, args, ctx):
        import re

        from okami.integrations.remote import _check_host
        alias = str(args.get("alias") or "").strip()
        host = str(args.get("host") or "").strip()
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$", alias):
            return ToolResult(False, "alias inválido — use letras/dígitos/._- (ex.: prod).", effect=False)
        try:
            _check_host(host)                          # recusa host hostil (-oProxyCommand=… etc.)
        except ValueError as e:
            return ToolResult(False, f"host inválido: {e}", effect=False)
        via = str(args.get("via") or "").strip().lower() or ("ssh" if "@" in host else "tailscale")
        if via not in ("ssh", "tailscale"):
            return ToolResult(False, "via deve ser 'ssh' ou 'tailscale'.", effect=False)
        try:
            from okami.config import set_local
            p = set_local(f"remote.hosts.{alias}", {"host": host, "via": via})
        except Exception as e:  # noqa: BLE001
            from okami.core.redact import redact
            return ToolResult(False, f"não consegui salvar o remote: {redact(str(e))}", effect=False)
        return ToolResult(True, f"✓ remote '{alias}' → {host} (via {via}) cadastrado em {p.name}. Conecte "
                          f"com remote_connect host={alias}. (vale após o próximo reload de config — "
                          "use restart_gateway se precisar agora).", effect=True)


class RemoteConnect(Tool):
    name = "remote_connect"
    description = (
        "Conecta a uma MÁQUINA REMOTA (via Tailscale SSH ou ssh) — depois disso suas tools de arquivo e "
        "shell (read_file/write_file/edit_file/list_dir/run_shell) operam NESSA máquina (configurar, ajustar, "
        "deploy, etc.). Passe um alias de remote.hosts ou um host (só no terminal do dono). NO TELEGRAM só "
        "aliases liberados funcionam. remote_disconnect volta ao local. Os mesmos freios de segurança (rm "
        "catastrófico, .env/.ssh) valem no host remoto."
    )
    args_schema = {"host": "alias de remote.hosts (ex.: prod) OU host cru (ex.: user@maquina) — só no terminal"}
    required = ("host",)

    def run(self, args, ctx):
        host = args.get("host")
        if not isinstance(host, str) or not host.strip():
            return ToolResult(False, "remote_connect exige 'host' (alias de remote.hosts ou user@maquina).",
                              effect=False)
        from okami.integrations.remote import resolve_remote
        try:
            rt = resolve_remote(_remote_cfg(ctx), host, is_terminal=_is_terminal(ctx))
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        health = rt.health_check()                       # falha cedo se host/config estiver errado
        if health.returncode != 0 or "okami-remote-ok" not in health.output:
            from okami.core.redact import redact
            return ToolResult(False, f"não conectei a {rt.host} (via {rt.via}): "
                              f"{redact(health.output).strip()[:200] or 'sem resposta'}", effect=False)
        ctx.remote = rt
        fn = getattr(ctx, "set_remote", None)
        if fn is not None:
            fn(rt)                                        # persiste na sessão (sobrevive ao turno)
        return ToolResult(True, f"📡 conectado a '{rt.alias}' ({rt.host}, via {rt.via}). Suas tools de arquivo "
                          "e shell agora operam NESSA máquina. remote_disconnect volta ao local.", effect=True)


class RemoteDisconnect(Tool):
    name = "remote_disconnect"
    description = ("Desconecta da máquina remota e volta a operar LOCALMENTE (suas tools voltam a mexer "
                  "na máquina onde o Okami roda).")
    args_schema = {}
    required = ()

    def run(self, args, ctx):
        rt = getattr(ctx, "remote", None)
        if rt is not None:
            try:
                rt.close()
            except Exception:  # noqa: BLE001 — fechar conexão nunca derruba o turno
                pass
        ctx.remote = None
        fn = getattr(ctx, "set_remote", None)
        if fn is not None:
            fn(None)                                     # limpa a sessão
        alias = getattr(rt, "alias", None)
        msg = f"voltei ao ambiente LOCAL (desconectado de '{alias}')." if rt else "já estava no local."
        return ToolResult(True, msg, effect=True)
