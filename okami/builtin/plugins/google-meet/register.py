"""google-meet (plugin builtin) — port MÍNIMO do plugin google_meet do Hermes.

O Hermes original (hermes-agent/plugins/google_meet/, ~950 linhas em tools.py+cli.py+process_manager.py+
audio_bridge.py+node/) spawna um Chromium headless via Playwright, entra na call, ativa legendas ao vivo
e faz scraping delas pra um arquivo de transcript; v2 acrescenta duplex de áudio em tempo real (o agente
FALA na reunião) via bridge OpenAI Realtime + BlackHole (macOS) / PulseAudio null-sink (Linux); v3 deixa o
bot rodar num "node host" remoto (gateway numa máquina Linux, Chrome com perfil logado noutra).

Nada disso está portado aqui — falta Playwright + Chromium, um process_manager que orquestre o subprocesso
do bot, o scraper de legendas do Meet, e (pra v2) a ponte de áudio. Em vez de copiar isso quebrado, este
port registra a MESMA superfície de tools que o Hermes expõe ao modelo (`meet_join`, `meet_status`,
`meet_transcript`, `meet_leave` — omite `meet_say`, que só faz sentido com a ponte de áudio realtime que
não existe aqui) e cada uma devolve uma mensagem clara do que falta, em vez de estourar exceção ou fingir
sucesso. Mantém a superfície ESTÁVEL pro modelo (ele já pode "tentar" e recebe uma explicação, não um erro
genérico) e documenta o caminho pra portar de verdade depois.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult

_NOT_IMPLEMENTED = (
    "[google-meet] port mínimo: essa tool está REGISTRADA mas a orquestração real não foi portada do "
    "Hermes. Falta: (1) `pip install playwright && playwright install chromium`; (2) um process_manager "
    "que suba/monitore/derrube o bot como subprocesso; (3) o scraper de legendas ao vivo do Meet "
    "(Playwright + DOM do meet.google.com); (4) pra falar na call (mode=realtime), uma ponte de áudio "
    "(BlackHole no macOS / PulseAudio null-sink no Linux) + cliente OpenAI Realtime. Referência completa: "
    "hermes-agent/plugins/google_meet/ (tools.py, process_manager.py, audio_bridge.py, node/)."
)


class MeetJoin(Tool):
    name = "meet_join"
    description = (
        "Entra numa call do Google Meet e transcreve legendas ao vivo (port MÍNIMO — orquestração real "
        "não implementada nesta build; ver mensagem de retorno). Só aceita URLs meet.google.com "
        "explícitas — sem varredura de calendário, sem discagem automática."
    )
    args_schema = {
        "url": "URL completa https://meet.google.com/... (obrigatório)",
        "mode": "'transcribe' (padrão, só escuta) ou 'realtime' (também fala — não portado)",
        "guest_name": "nome de exibição ao entrar como convidado",
        "duration": "duração máxima antes de sair sozinho, ex.: '30m', '2h'",
    }
    required = ("url",)

    def run(self, args, ctx):
        url = str(args.get("url") or "").strip()
        if not url:
            return ToolResult(False, "meet_join: 'url' precisa ser uma URL meet.google.com não-vazia.")
        if "meet.google.com" not in url:
            return ToolResult(False, "meet_join: só URLs meet.google.com são aceitas (explicit-by-design).")
        return ToolResult(False, _NOT_IMPLEMENTED)


class MeetStatus(Tool):
    name = "meet_status"
    description = "Reporta se o bot do Google Meet está vivo e o progresso da transcrição (port MÍNIMO)."
    args_schema = {}

    def run(self, args, ctx):
        return ToolResult(False, _NOT_IMPLEMENTED)


class MeetTranscript(Tool):
    name = "meet_transcript"
    description = "Lê o transcript atual da call (opcionalmente últimas N linhas) (port MÍNIMO)."
    args_schema = {"last_n": "quantas linhas finais do transcript devolver (opcional)"}

    def run(self, args, ctx):
        return ToolResult(False, _NOT_IMPLEMENTED)


class MeetLeave(Tool):
    name = "meet_leave"
    description = "Sinaliza pro bot sair da call de forma limpa (port MÍNIMO)."
    args_schema = {}

    def run(self, args, ctx):
        return ToolResult(False, _NOT_IMPLEMENTED)


_TOOLS = (MeetJoin, MeetStatus, MeetTranscript, MeetLeave)


def register(ctx) -> None:
    for cls in _TOOLS:
        ctx.register_tool(cls())
