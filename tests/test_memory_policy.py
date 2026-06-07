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


# ---------------------------------------------------------------- Do-NOT-capture (Hermes anti-lixo)
def test_do_not_capture_blocks_env_failures_and_negative_tool_claims():
    from okami.memory.policy import do_not_capture
    # (1) falhas de AMBIENTE/setup — o usuário conserta, não é regra durável
    for t in ("docker não está instalado", "command not found: ffmpeg", "ModuleNotFoundError: no module named x",
              "permission denied ao abrir /etc", "no such file or directory"):
        assert do_not_capture(t), t
    # (2) claim NEGATIVO sobre tool do agente — vira refusal self-citado
    for t in ("a ferramenta browser não funciona", "run_shell is broken", "o docker está quebrado",
              "playwright unavailable", "the mcp tool doesn't work"):
        assert do_not_capture(t), t


def test_do_not_capture_keeps_real_knowledge():
    from okami.memory.policy import do_not_capture
    # bug report do PRODUTO do usuário NÃO é claim sobre tool do agente → fica
    assert not do_not_capture("o botão de login do app do usuário não funciona em Safari")
    assert not do_not_capture("o usuário prefere tabs a espaços")
    assert not do_not_capture("decidimos usar Postgres")
    assert not do_not_capture("para rodar, instale o ffmpeg antes")     # o FIX é capturável


def test_prepare_blocks_auto_garbage_but_not_user_force():
    # auto (agente/reflexão) → barrado; usuário explícito (force) → salva mesmo assim
    assert prepare("a ferramenta browser não funciona", source="agent") is None
    assert prepare("docker não está instalado", source="reflection") is None
    forced = prepare("a ferramenta browser não funciona", source="cli", force=True)
    assert forced is not None                                            # override do usuário vence
