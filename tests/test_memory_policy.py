"""Política de escrita de memória: classifica a categoria e barra efêmero/trivial."""

from __future__ import annotations

from okami.memory.policy import (
    DECISION, ERROR, FACT, PREFERENCE, SKILL, TEMP, classify, prepare, should_persist,
)


def test_classify_categories():
    assert classify("o usuário prefere ShadCN para frontend") == PREFERENCE
    assert classify("decidimos usar Postgres no lugar de Mongo") == DECISION
    assert classify("o build quebra quando roda no CI") == ERROR
    assert classify("como configurar o deploy passo a passo") == SKILL
    assert classify("por agora foca só no backend") == TEMP
    assert classify("o deploy usa Vercel") == FACT


def test_should_persist_gates_temp_and_trivial():
    assert should_persist("um fato suficientemente longo", FACT) is True
    assert should_persist("curto", FACT) is False                 # < 8 chars → trivial
    assert should_persist("por agora foca nisso", TEMP) is False   # efêmero


def test_prepare_classifies_and_gates():
    item = prepare("o usuário prefere tabs a espaços", source="agent")
    assert item is not None and item.kind == PREFERENCE and item.source == "agent"
    assert prepare("por agora ignore isso aqui", source="agent") is None   # efêmero não persiste
    assert prepare("   ", source="agent") is None                          # vazio
    # kind específico é respeitado; genérico (fact) é reclassificado:
    assert prepare("qualquer coisa longa o bastante", kind="summary").kind == "summary"
    assert prepare("decidimos migrar pra uv agora", kind="fact").kind == DECISION
    # force ignora o gate de efêmero (usuário explícito), mas ainda classifica:
    forced = prepare("por agora isto é um teste", source="cli", force=True)
    assert forced is not None and forced.kind == TEMP


def test_remember_tool_routes_through_policy(tmp_path):
    """A tool `remember` NÃO guarda contexto efêmero, e classifica o que guarda."""
    from okami.core.tools import RememberFact, ToolContext

    class _Mem:
        def __init__(self):
            self.items = []

        def write(self, item):
            self.items.append(item)

    mem = _Mem()
    ctx = ToolContext(workspace=tmp_path, memory=mem)
    eph = RememberFact().run({"text": "por agora ignore isso"}, ctx)
    assert eph.ok and not eph.effect and not mem.items            # efêmero → nada guardado
    kept = RememberFact().run({"text": "o usuário prefere TypeScript no projeto"}, ctx)
    assert kept.ok and kept.effect and mem.items[0].kind == PREFERENCE
