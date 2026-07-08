"""Prompt caching Anthropic EXPLÍCITO (pesquisa #5 item 58, Hermes: ~75% economia de input).

Modelos Claude roteados via litellm ganham `cache_control: ephemeral` no system + nas 3 últimas
mensagens (máx. 4 breakpoints da API). Outros providers ficam INTOCADOS (formato de lista com
cache_control não é universal). Transports (claude_cli/codex_oauth) não passam por aqui.
"""
from __future__ import annotations

from okami.llm.providers import apply_prompt_caching


def _msgs(n: int = 6) -> list[dict]:
    out = [{"role": "system", "content": "sys"}]
    for i in range(n):
        out.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})
    return out


def _has_cache(m: dict) -> bool:
    c = m.get("content")
    return isinstance(c, list) and any(isinstance(p, dict) and p.get("cache_control") for p in c)


def test_marks_system_and_last_three_for_claude():
    out = apply_prompt_caching(_msgs(), "anthropic/claude-sonnet-4-6")
    assert _has_cache(out[0])                                # system
    assert all(_has_cache(m) for m in out[-3:])              # últimas 3
    assert not any(_has_cache(m) for m in out[1:-3])         # meio fica liso (máx 4 breakpoints)


def test_marked_text_preserved():
    out = apply_prompt_caching(_msgs(), "claude-opus-4-8")
    assert out[0]["content"][0]["text"] == "sys"
    assert out[-1]["content"][0]["text"] == "m5"


def test_non_anthropic_models_untouched():
    msgs = _msgs()
    out = apply_prompt_caching(msgs, "openai/gpt-5")
    assert out is msgs                                       # nem copia — zero custo no caminho comum


def test_original_list_not_mutated():
    msgs = _msgs()
    apply_prompt_caching(msgs, "anthropic/claude-sonnet-4-6")
    assert all(isinstance(m["content"], str) for m in msgs)


def test_short_conversation_no_crash():
    out = apply_prompt_caching([{"role": "user", "content": "oi"}], "anthropic/claude-haiku-4-5")
    assert _has_cache(out[0])


def test_cache_marker_default_is_5min(monkeypatch):
    # #9: default mantém o comportamento atual (sem ttl explícito = 5min da API).
    monkeypatch.delenv("OKAMI_CACHE_TTL", raising=False)
    from okami.llm.providers import _cache_marker
    assert _cache_marker() == {"type": "ephemeral"}


def test_cache_marker_1h_optin(monkeypatch):
    # OKAMI_CACHE_TTL=1h liga o TTL estendido (daemon ocioso sobrevive ao cache).
    monkeypatch.setenv("OKAMI_CACHE_TTL", "1h")
    from okami.llm.providers import _cache_marker
    assert _cache_marker().get("ttl") == "1h"


# ---- FIX 2: cache_control não desperdiça breakpoint em mensagem vazia (mirror Hermes _can_carry_marker) ----

def test_skips_empty_assistant_toolcall_message():
    # turno tool-heavy: assistant emite só tool_calls (content vazio) — sem TEXTO onde grudar o marcador.
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "faça X"},
        {"role": "assistant", "content": ""},                 # pure tool_call — não carrega marcador
        {"role": "tool", "content": ""},                      # tool-result vazio — idem
        {"role": "user", "content": "continue"},
    ]
    out = apply_prompt_caching(msgs, "anthropic/claude-sonnet-4-6")
    assert _has_cache(out[0])                                 # system
    assert not _has_cache(out[2])                             # assistant vazio: SEM marcador
    assert not _has_cache(out[3])                             # tool vazio: SEM marcador
    assert _has_cache(out[1])                                 # os 3 breakpoints restantes vão pro que TEM
    assert _has_cache(out[4])                                 # conteúdo real (user "faça X" e "continue")


def test_skips_empty_list_content_message():
    # content = lista vazia ou lista cujo último bloco não é texto (ex.: só imagem) — idem: pula.
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "m1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": []},                  # lista vazia — sem onde grudar
        {"role": "user", "content": "m3"},
    ]
    out = apply_prompt_caching(msgs, "anthropic/claude-sonnet-4-6")
    assert not _has_cache(out[3])
    assert _has_cache(out[1]) and _has_cache(out[2]) and _has_cache(out[4])


def test_can_carry_cache_marker_helper():
    from okami.llm.providers import _can_carry_cache_marker
    assert _can_carry_cache_marker({"content": "oi"}) is True
    assert _can_carry_cache_marker({"content": ""}) is False
    assert _can_carry_cache_marker({"content": None}) is False
    assert _can_carry_cache_marker({"content": []}) is False
    assert _can_carry_cache_marker({"content": [{"type": "image_url", "image_url": {}}]}) is False
    assert _can_carry_cache_marker({"content": [{"type": "text", "text": "oi"}]}) is True
    assert _can_carry_cache_marker({"content": [{"type": "text", "text": "  "}]}) is False
