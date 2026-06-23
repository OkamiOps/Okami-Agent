"""Paridade Hermes (prompt_builder telegram block): o que FAZ o modelo formatar certo no Telegram não é
o renderer — é a DIREÇÃO no system prompt. Hermes enquadra como IDENTIDADE de plataforma ('você está no
Telegram'), garante que o markdown É convertido (→ use), e dá a regra decisiva: estruturado, não paredão."""
from __future__ import annotations

from okami.core import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.tools.registry import default_registry


def _tg_prompt():
    return build_system_prompt(Task(goal="relatório do gog"), default_registry(),
                               surface="telegram", model="minimax/MiniMax-M3").lower()


def test_telegram_prompt_frames_platform_identity():
    p = _tg_prompt()
    assert "telegram" in p
    assert "convert" in p or "convertid" in p          # garante ao modelo que o markdown VAI renderizar


def test_telegram_prompt_demands_structured_over_dense():
    p = _tg_prompt()
    assert "paredão" in p or "parágrafo" in p          # regra anti-wall-of-text
    assert "estrutura" in p                             # "prefira ESTRUTURADO"


def test_telegram_prompt_allows_tables_now():
    # antes dizia 'NÃO tabela'; agora o to_html renderiza tabela → o modelo PODE usar (paridade Hermes)
    p = _tg_prompt()
    assert "tabela" in p
