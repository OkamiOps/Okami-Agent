"""teams (plugin builtin) — port MÍNIMO do plugin teams_pipeline do Hermes.

O Hermes original (hermes-agent/plugins/teams_pipeline/, ~2.4k linhas) é uma pipeline Graph-backed
completa: assina webhooks do Microsoft Graph pra eventos de reunião, baixa transcript/gravação, resume
via LLM, escreve o resumo em Notion/Linear e/ou responde no chat do Teams — tudo com um store durável
(job state em disco, sobrevive a restart) e um CLI de operador (`hermes teams-pipeline ...`) pra listar
jobs, inspecionar runs, reprocessar, validar config do Graph e manter as subscriptions vivas.

Nada disso está portado aqui — falta o app registration no Microsoft Graph (tenant/client/secret), a
camada de subscriptions de webhook, download de artefato de reunião, resumo via LLM e os sinks de saída.
Em vez de copiar a pipeline quebrada, este port registra duas tools honestas: uma que diagnostica quais
credenciais do Graph já estão no ambiente (`teams_pipeline_status`) e um stub estável pra pedir resumo de
reunião (`teams_meeting_summary`) que hoje sempre explica o que falta em vez de fingir que funciona.
"""
from __future__ import annotations

import os

from okami.core.tools.base import Tool, ToolResult

# Nomes de env var que a pipeline original precisa pra autenticar no Microsoft Graph (client credentials
# flow). Não são lidos de config.yaml aqui de propósito — é só um DIAGNÓSTICO, não uma integração real.
_GRAPH_ENV_VARS = ("TEAMS_GRAPH_TENANT_ID", "TEAMS_GRAPH_CLIENT_ID", "TEAMS_GRAPH_CLIENT_SECRET")

_NOT_IMPLEMENTED = (
    "[teams] port mínimo: essa tool está REGISTRADA mas a pipeline real não foi portada do Hermes. "
    "Falta: assinatura de webhook do Microsoft Graph pra eventos de reunião, download de "
    "transcript/gravação, resumo via LLM, e os sinks de saída (Notion/Linear/resposta no Teams) — tudo "
    "isso com um job store durável (sobrevive a restart) no Hermes original. Referência completa: "
    "hermes-agent/plugins/teams_pipeline/ (pipeline.py, subscriptions.py, store.py, meetings.py)."
)


class TeamsPipelineStatus(Tool):
    name = "teams_pipeline_status"
    description = (
        "Diagnostica o pipeline de reuniões do Microsoft Teams (port MÍNIMO do teams_pipeline do "
        "Hermes) — reporta quais credenciais do Microsoft Graph estão presentes no ambiente. Não "
        "executa a pipeline (não portada); é só um check de pré-requisito."
    )
    args_schema = {}

    def run(self, args, ctx):
        missing = [v for v in _GRAPH_ENV_VARS if not os.environ.get(v)]
        lines = [
            "[teams-pipeline] port mínimo — a orquestração completa (webhooks do Graph, download de "
            "transcript/gravação, resumo via LLM, sinks Notion/Linear/Teams) NÃO foi portada.",
        ]
        if missing:
            lines.append("Credenciais Microsoft Graph ausentes: " + ", ".join(missing))
        else:
            lines.append(
                "Credenciais Microsoft Graph presentes no ambiente, mas a orquestração da pipeline "
                "(store durável + subscriptions + sinks) ainda não existe nesta build."
            )
        lines.append(
            "Referência completa: hermes-agent/plugins/teams_pipeline/ "
            "(pipeline.py, subscriptions.py, store.py, meetings.py)."
        )
        return ToolResult(True, "\n".join(lines))


class TeamsMeetingSummary(Tool):
    name = "teams_meeting_summary"
    description = (
        "Pede o resumo de uma reunião do Teams a partir da URL de entrada ou do ID da reunião (port "
        "MÍNIMO — a pipeline de resumo real não foi implementada nesta build; ver mensagem de retorno)."
    )
    args_schema = {"meeting_ref": "URL de entrada (joinWebUrl) ou ID da reunião do Teams"}
    required = ("meeting_ref",)

    def run(self, args, ctx):
        ref = str(args.get("meeting_ref") or "").strip()
        if not ref:
            return ToolResult(False, "teams_meeting_summary: 'meeting_ref' precisa ser uma string não-vazia.")
        return ToolResult(False, _NOT_IMPLEMENTED)


_TOOLS = (TeamsPipelineStatus, TeamsMeetingSummary)


def register(ctx) -> None:
    for cls in _TOOLS:
        ctx.register_tool(cls())
