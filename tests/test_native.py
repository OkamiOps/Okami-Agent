"""Native tool-calls (FUNDAÇÃO testável) + fallback configurado.

O harness passa a CONSUMIR tool-calls nativas se o provider as devolver (function-calling), convivendo
com o protocolo JSON-em-texto (zero regressão). O caminho do TRANSPORTE codex (enviar `tools` + parsear
`function_call`) muda o protocolo de mensagens e precisa de verificação AO VIVO — fica explícito.
"""

from __future__ import annotations

from pathlib import Path

from okami.core import Harness, Task
from okami.core.tools import default_registry, openai_tools
from okami.llm.usage import Completion


def test_tool_to_openai_schema():
    reg = default_registry()
    sch = reg["write_file"].to_openai_schema()
    f = sch["function"]
    assert sch["type"] == "function" and f["name"] == "write_file"
    assert "path" in f["parameters"]["properties"] and "path" in f["parameters"]["required"]
    tools = openai_tools(reg)
    assert isinstance(tools, list) and any(t["function"]["name"] == "read_file" for t in tools)


class _NativeGen:
    def __init__(self, items):
        self.items = list(items)

    def __call__(self, messages, schema=None):
        return self.items.pop(0) if self.items else "ok"


def test_harness_executes_native_tool_calls(tmp_path):
    """generate devolve um Completion com tool_calls (nativo) → o harness EXECUTA a tool (sem JSON-texto)."""
    items = [
        Completion(tool_calls=[{"id": "1", "name": "write_file",
                                "arguments": '{"path":"a.txt","content":"oi"}'}]),
        '```json\n{"tool":"respond","args":{"message":"feito"}}\n```',   # depois, fala (protocolo JSON)
    ]
    Harness(_NativeGen(items), Task(goal="cria a.txt"), tmp_path, approve=lambda r: True).run()
    assert (tmp_path / "a.txt").read_text() == "oi"     # tool nativa executada


def test_okami_yaml_has_fallback_chains():
    """fallback agora está CONFIGURADO no okami.yaml → o failover (que já existia) realmente dispara."""
    from okami.config import load_config
    cfg = load_config(Path("okami.yaml"))
    assert "claude" in cfg.providers["codex"].fallback
    assert "lmstudio" in cfg.providers["minimax"].fallback
