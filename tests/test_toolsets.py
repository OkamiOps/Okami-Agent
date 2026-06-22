"""Toolsets completos (pesquisa #5 item 27, paridade Hermes): check_fn de DISPONIBILIDADE
(tool com dependência faltando sai do registro com razão, em vez de falhar na cara do modelo)
+ tool_search (schemas SOB DEMANDA — MCP numeroso vira 1 linha no prompt; o schema completo
vem via tool_search quando o agente precisa).
"""
from __future__ import annotations

from okami.core.harness.prompt import build_system_prompt
from okami.core.harness.models import Task
from okami.core.tools import Tool, ToolContext, default_registry
from okami.core.tool_policy import prune_unavailable


class _NeedsDep(Tool):
    name = "needs_dep"
    description = "tool com dependência opcional"
    args_schema = {}

    def check(self):
        return "lib 'foo' não instalada (pip install foo)"


class _Fine(Tool):
    name = "fine"
    description = "tool sempre disponível"
    args_schema = {}


# ------------------------------------------------------------------ check_fn
def test_prune_unavailable_drops_with_reason():
    msgs = []
    reg = {"needs_dep": _NeedsDep(), "fine": _Fine()}
    out = prune_unavailable(reg, emit=msgs.append)
    assert "needs_dep" not in out and "fine" in out
    assert msgs and "foo" in msgs[0]


def test_default_tools_have_no_check_or_pass():
    # nenhuma tool nativa do registro default pode sumir por check num ambiente de teste comum —
    # exceto as que dependem de extra/credencial REAL: generate_image (login codex), audio_analyze
    # (extra `voice`/faster-whisper), text_to_speech (edge-tts), computer_use (opt-in + backend de
    # desktop) e as integrações config-driven generate_video/homeassistant/feishu_doc_read/x_search
    # (sem a integração no okami.yaml → indisponíveis). Degradam via check() de propósito.
    reg = default_registry()
    out = prune_unavailable(reg, emit=lambda m: None)
    missing = set(reg) - set(out)
    assert missing <= {"generate_image", "audio_analyze", "text_to_speech", "computer_use",
                       "generate_video", "homeassistant", "feishu_doc_read", "x_search"}


def test_generate_image_check_depends_on_codex_login(monkeypatch):
    from okami.core.tools.agentic import GenerateImage
    monkeypatch.setattr("okami.llm.oauth.codex_access_token", lambda: None)
    assert GenerateImage().check() is not None           # sem login → indisponível com razão
    monkeypatch.setattr("okami.llm.oauth.codex_access_token", lambda: "tok")
    assert GenerateImage().check() is None


# ------------------------------------------------------------------ tool_search
def test_tool_search_returns_full_schema(tmp_path):
    from okami.core.tools.toolsearch import ToolSearch
    reg = default_registry()
    ctx = ToolContext(workspace=tmp_path, registry=reg)
    res = ToolSearch().run({"query": "patch"}, ctx)
    assert res.ok
    assert "apply_patch" in res.output and "envelope" in res.output   # descrição + args completos


def test_tool_search_unknown_query_lists_names(tmp_path):
    from okami.core.tools.toolsearch import ToolSearch
    ctx = ToolContext(workspace=tmp_path, registry=default_registry())
    res = ToolSearch().run({"query": "zzz-nada-disso"}, ctx)
    assert not res.ok
    assert "read_file" in res.output                     # lista o que existe p/ orientar


def test_tool_search_registered():
    assert "tool_search" in default_registry()


# ------------------------------------------------------------------ disclosure de MCP no prompt
class _FakeMcp(Tool):
    mcp = True

    def __init__(self, n):
        self.name = f"srv_tool_{n}"
        self.description = ("Primeira frase da tool. Um schema gigante com mil detalhes que "
                            "não precisa morar no prompt o tempo todo. " * 3)
        self.args_schema = {"a": "arg a", "b": "arg b"}


def test_many_mcp_tools_collapse_to_one_line(tmp_path):
    reg = default_registry()
    for i in range(10):
        t = _FakeMcp(i)
        reg[t.name] = t
    prompt = build_system_prompt(Task(goal="x"), reg, workspace=tmp_path)
    assert "srv_tool_3" in prompt                        # a tool aparece…
    assert prompt.count("schema gigante") == 0           # …mas SEM a descrição longa
    assert "tool_search" in prompt                       # e o caminho p/ o schema completo é ensinado


def test_few_mcp_tools_keep_full_description(tmp_path):
    reg = default_registry()
    t = _FakeMcp(1)
    reg[t.name] = t
    prompt = build_system_prompt(Task(goal="x"), reg, workspace=tmp_path)
    assert "schema gigante" in prompt                    # poucos MCP → descrição completa (sem custo)
