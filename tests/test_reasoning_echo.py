"""Multi-vendor (DeepSeek-reasoner / Kimi-Moonshot / MiMo em thinking-mode — vendors do dono): a API EXIGE um
campo reasoning_content em CADA mensagem assistant com tool_calls no multi-turno, senão HTTP 400 ('The
reasoning_content in the thinking mode must be passed back'). O Okami TIRA reasoning_content de tudo (sanitize)
→ quebrava esses vendors. _ensure_reasoning_echo garante o campo (placeholder ' ' do Hermes) p/ as famílias
que exigem, sem tocar em cloud/OpenAI/Anthropic."""
from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.providers import _ensure_reasoning_echo


def _asst_with_tool_call():
    return [{"role": "user", "content": "faça X"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function",
                                                                 "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "ok"}]


def test_deepseek_reasoner_gets_reasoning_content_placeholder():
    pc = ProviderConfig(name="ds", model="deepseek-reasoner")
    out = _ensure_reasoning_echo(_asst_with_tool_call(), pc)
    assert out[1]["reasoning_content"] == " "          # campo garantido → sem HTTP 400


def test_cloud_openai_untouched():
    pc = ProviderConfig(name="oai", model="gpt-4o")
    out = _ensure_reasoning_echo(_asst_with_tool_call(), pc)
    assert "reasoning_content" not in out[1]            # família que NÃO exige → nada muda


def test_strip_mode_never_adds():
    pc = ProviderConfig(name="ds", model="deepseek-reasoner", reasoning_echo="strip")
    out = _ensure_reasoning_echo(_asst_with_tool_call(), pc)
    assert "reasoning_content" not in out[1]


def test_require_mode_adds_for_any_provider():
    pc = ProviderConfig(name="x", model="qualquer-modelo", reasoning_echo="require")
    out = _ensure_reasoning_echo(_asst_with_tool_call(), pc)
    assert out[1]["reasoning_content"] == " "


def test_existing_reasoning_content_preserved():
    pc = ProviderConfig(name="ds", model="kimi-thinking")
    msgs = _asst_with_tool_call()
    msgs[1]["reasoning_content"] = "raciocínio real"
    out = _ensure_reasoning_echo(msgs, pc)
    assert out[1]["reasoning_content"] == "raciocínio real"   # não sobrescreve o real


def test_assistant_without_tool_calls_untouched():
    pc = ProviderConfig(name="ds", model="deepseek-reasoner")
    msgs = [{"role": "assistant", "content": "só texto, sem tool"}]
    out = _ensure_reasoning_echo(msgs, pc)
    assert "reasoning_content" not in out[0]            # só msg COM tool_calls precisa do campo
