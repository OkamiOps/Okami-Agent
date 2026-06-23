"""Tool-gating (sweep #5/#6): o payload NATIVO tem de levar o registry FILTRADO por surface em TODO caminho
— generate, ESCALATE e o RETRY de schema. Senão o Telegram (que nega run_shell/spawn) recebe essas tools no
payload, o modelo as chama → 'ferramenta inválida' (turno desperdiçado, parece 'não segue regra')."""
from __future__ import annotations

import okami.llm.providers as providers
from okami.core.tools import ReadFile, Tool, ToolResult, openai_tools
from okami.runner import _native_tools_for


class _RespondT(Tool):
    name = "respond"
    description = "responde"
    args_schema = {"text": "t"}

    def run(self, args, ctx):  # pragma: no cover
        return ToolResult(True, args.get("text", ""))


# ----------------------------------------------------------------- #5 generate E escalate injetam filtrado
def test_native_tools_for_injects_filtered_registry(monkeypatch):
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)
    reg = {"read_file": ReadFile(), "respond": _RespondT()}
    eff = _native_tools_for(object(), reg, {})
    names = {t["function"]["name"] for t in eff["tools"]}
    assert names == {"read_file", "respond"}                 # SÓ o registry filtrado (não o default inteiro)


def test_native_tools_for_skips_when_not_supported(monkeypatch):
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: False)
    assert "tools" not in _native_tools_for(object(), {"read_file": ReadFile()}, {})


def test_native_tools_for_does_not_overwrite_caller(monkeypatch):
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)
    eff = _native_tools_for(object(), {"read_file": ReadFile()}, {"tools": ["JÁ_PASSADO"]})
    assert eff["tools"] == ["JÁ_PASSADO"]                     # idempotente


# ----------------------------------------------------------------- #6 retry de schema preserva o filtrado
def test_schema_retry_keeps_filtered_tools_not_default(monkeypatch):
    filtered = openai_tools({"read_file": ReadFile(), "respond": _RespondT()})   # subset (sem run_shell)
    seen = {}

    class _SchemaErr(Exception):
        pass

    def fake_completion(**kw):
        names = [t["function"]["name"] for t in kw.get("tools", [])]
        if not seen.get("retried"):
            seen["first_tools"] = names
            seen["retried"] = True
            raise _SchemaErr("invalid schema for function: grammar")   # bate em _SCHEMA_ERR_MARKERS
        seen["retry_tools"] = names

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": "ok", "tool_calls": None})(),
                                      "finish_reason": "stop"})()]
            usage = None
        return _R()

    monkeypatch.setattr(providers.litellm, "completion", fake_completion)
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)
    monkeypatch.setattr(providers.transports, "dispatch", lambda *a, **k: None)
    monkeypatch.setattr(providers, "apply_prompt_caching", lambda m, model: m)
    monkeypatch.setattr(providers, "_response_format", lambda pc, rs: None)
    monkeypatch.setattr(providers, "_kwargs", lambda pc, messages, **kw: {"messages": messages, **kw})

    class _PC:
        tool_choice = "required"
        model = "test/model"
        name = "testprov"
    # caller passa o registry FILTRADO no overrides (como o runner faz)
    providers._complete_one(_PC(), [{"role": "user", "content": "oi"}], "m", None,
                            {"tools": filtered})
    # no retry, NÃO pode ter virado o default inteiro — continua só o subset filtrado
    assert seen["retry_tools"] == seen["first_tools"]
    assert "run_shell" not in seen["retry_tools"]
