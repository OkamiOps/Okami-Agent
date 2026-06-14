"""Item 12 — quirks declarativos por provider (reasoning_style, vision_tool_messages, omit_temperature).

São campos OPT-IN no ProviderConfig consumidos em `_kwargs`. Default = comportamento de hoje
(reasoning_effort puro, temperature intacta, image_url em msg tool preservado). Cada teste fixa um
quirk e prova que o kwargs SAI do jeito que aquele provider espera — sem tocar nos outros caminhos."""

from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm import providers


def _pc(**kw) -> ProviderConfig:
    base = {"name": "p", "model": "openai/whatever"}
    base.update(kw)
    return ProviderConfig(**base)


def _msgs():
    return [{"role": "user", "content": "oi"}]


# --- reasoning_style ----------------------------------------------------------

def test_reasoning_style_thinking_emits_thinking_block_not_effort():
    pc = _pc(reasoning_style="thinking", reasoning_effort="high")
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert "reasoning_effort" not in kw          # estilo thinking NÃO usa reasoning_effort
    assert kw["thinking"]["type"] == "enabled"
    assert kw["thinking"]["budget_tokens"] > 0   # effort virou budget de tokens


def test_reasoning_style_none_omits_both():
    pc = _pc(reasoning_style="none", reasoning_effort="high")
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert "reasoning_effort" not in kw
    assert "thinking" not in kw


def test_default_style_with_effort_keeps_reasoning_effort_no_thinking():
    # GUARD DE REGRESSÃO: sem reasoning_style declarado, segue o comportamento antigo.
    pc = _pc(reasoning_effort="high")
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert kw.get("reasoning_effort") == "high"
    assert "thinking" not in kw


def test_reasoning_style_explicit_reasoning_effort_keeps_it():
    pc = _pc(reasoning_style="reasoning_effort", reasoning_effort="low")
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert kw.get("reasoning_effort") == "low"
    assert "thinking" not in kw


def test_thinking_strips_thinking_when_no_effort():
    # estilo thinking sem effort declarado → não inventa budget (sem reasoning_effort, sem thinking).
    pc = _pc(reasoning_style="thinking")
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert "reasoning_effort" not in kw
    assert "thinking" not in kw


# --- omit_temperature ---------------------------------------------------------

def test_omit_temperature_strips_from_params():
    pc = _pc(omit_temperature=True, params={"temperature": 0.7})
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert "temperature" not in kw


def test_omit_temperature_strips_from_override():
    # um override /think (ou caller) não pode REINTRODUZIR temperature num modelo que a recusa.
    pc = _pc(omit_temperature=True)
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None, temperature=0.9)
    assert "temperature" not in kw


def test_temperature_preserved_when_not_omitted():
    # default: nada muda — temperature de params/override sobrevive.
    pc = _pc(params={"temperature": 0.3})
    kw = providers._kwargs(pc, _msgs(), stream=False, model=None)
    assert kw["temperature"] == 0.3
    kw2 = providers._kwargs(_pc(), _msgs(), stream=False, model=None, temperature=0.5)
    assert kw2["temperature"] == 0.5


# --- vision_tool_messages -----------------------------------------------------

def _tool_msg_with_image():
    return [
        {"role": "user", "content": "olha isso"},
        {"role": "tool", "tool_call_id": "x", "content": [
            {"type": "text", "text": "resultado"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]},
    ]


def test_vision_tool_messages_false_strips_image_url_from_tool_role():
    pc = _pc(vision_tool_messages=False)
    kw = providers._kwargs(pc, _tool_msg_with_image(), stream=False, model=None)
    tool = [m for m in kw["messages"] if m.get("role") == "tool"][0]
    blocks = tool["content"]
    assert all(b.get("type") != "image_url" for b in blocks)  # imagem removida
    assert any(b.get("type") == "text" for b in blocks)       # texto preservado


def test_vision_tool_messages_default_keeps_image_url():
    pc = _pc()  # default True
    kw = providers._kwargs(pc, _tool_msg_with_image(), stream=False, model=None)
    tool = [m for m in kw["messages"] if m.get("role") == "tool"][0]
    assert any(b.get("type") == "image_url" for b in tool["content"])


def test_vision_tool_messages_false_leaves_user_image_intact():
    # só mexe em role=="tool" — imagem em msg de USER (vision normal) fica.
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "veja"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
    ]}]
    pc = _pc(vision_tool_messages=False)
    kw = providers._kwargs(pc, msgs, stream=False, model=None)
    user = kw["messages"][0]
    assert any(b.get("type") == "image_url" for b in user["content"])
