"""Paridade Hermes (think_scrubber): remover blocos de raciocínio <think>…</think> (e variantes) do TEXTO.
Sem isso: (a) o parser varre o raciocínio e pode EXECUTAR uma tool_call que o modelo só estava COGITANDO
(ex.: um rm dentro do <think>); (b) as tags vazam pra resposta visível ao usuário. Modelos reasoning
(minimax/deepseek/glm/qwen) inlineam <think> no content o tempo todo."""
from __future__ import annotations

from okami.core.harness.parsing import parse_actions, strip_think_blocks


def test_strip_closed_pair():
    assert strip_think_blocks("<think>raciocínio interno</think>resposta") == "resposta"


def test_strip_keeps_text_around():
    assert strip_think_blocks("antes <thinking>x</thinking> depois") == "antes  depois".strip()


def test_strip_unterminated_open_to_eof():
    # aberto e não fechado (raciocínio cortado) → some até o fim
    assert strip_think_blocks("<think>pensando sem fechar e nunca termina") == ""


def test_strip_orphan_close():
    # fecha sem abrir (provider mandou só o fim) → corta o lixo antes do </think>
    assert strip_think_blocks("lixo de raciocínio</think>a resposta de verdade") == "a resposta de verdade"


def test_plain_text_unchanged():
    assert strip_think_blocks("texto normal, sem tags nenhuma") == "texto normal, sem tags nenhuma"


def test_parse_actions_ignores_draft_tool_call_inside_think():
    # CRÍTICO: uma tool_call RASCUNHO dentro do <think> NÃO pode ser executada
    txt = ('<think>acho que vou rodar {"tool":"run_shell","args":{"cmd":"rm -rf /"}}</think>'
           '```json\n{"tool":"read_file","args":{"path":"a.txt"}}\n```')
    acts = parse_actions(txt)
    assert len(acts) == 1
    assert acts[0].tool == "read_file"                     # só a ação REAL (fora do think) roda
    assert all("run_shell" != a.tool for a in acts)        # o rascunho rm foi descartado


def test_parse_actions_empty_when_only_think():
    assert parse_actions('<think>{"tool":"run_shell","args":{"cmd":"rm"}}</think>') == []
