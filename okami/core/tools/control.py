"""Tools TERMINAIS de controle: respond, task_complete, task_blocked, need_input."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool,
)


class Respond(Tool):
    name = "respond"
    description = ("FALA com o usuário (responder, opinar, perguntar, conversar) e encerra o turno. "
                   "É assim que você conversa — use sempre que for só diálogo, sem precisar agir.")
    args_schema = {"message": "sua mensagem ao usuário, no seu tom (VOICE/PERSONA)"}
    required = ("message",)
    terminal = True


class TaskComplete(Tool):
    name = "task_complete"
    description = "Conclui um TRABALHO com critérios. Só é aceito se os critérios de saída forem verificados."
    args_schema = {"summary": "resumo do que foi feito"}
    terminal = True


class TaskBlocked(Tool):
    name = "task_blocked"
    description = "Declara que está bloqueado, com a razão."
    args_schema = {"reason": "por que está bloqueado"}
    required = ("reason",)
    terminal = True


class NeedInput(Tool):
    name = "need_input"
    description = ("Pede uma informação ao usuário para poder continuar. Quando a resposta é uma "
                   "ESCOLHA, passe `options` (2-4 itens) — vira lista numerada e a pessoa responde '2'.")
    args_schema = {"question": "pergunta ao usuário",
                   "options": "(opc) lista de 2-4 opções p/ escolha numerada"}
    required = ("question",)
    terminal = True
