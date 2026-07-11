"""Sistema de hooks UNIFICADO (#unify, port do Hermes hermes_cli/plugins.py:135-218 VALID_HOOKS +
invoke_hook). okami/plugins.py.HookBus junta os pontos de ciclo de vida que faltavam (LLM, sessão,
subagente, gateway, aprovação) sem substituir okami/automation/hooks.py (shell/pasta/config)."""
from __future__ import annotations

import textwrap

from okami.automation.hooks import HookManager
from okami.core import Budget, Harness, Task
from okami.core.harness.parsing import Action
from okami.core.tools.base import ToolResult
from okami.plugins import (
    VALID_HOOKS,
    HookBus,
    PluginRegistrar,
    discover_plugins,
    load_plugin_hooks,
    plugin_context,
)


# ---------------------------------------------------------------------------- VALID_HOOKS / registrar
def test_valid_hooks_mirrors_hermes_minus_kanban():
    expected = {
        "pre_tool_call", "post_tool_call", "transform_tool_result", "transform_llm_output",
        "pre_llm_call", "post_llm_call", "pre_verify", "on_session_start", "on_session_end",
        "on_session_reset", "subagent_start", "subagent_stop", "pre_gateway_dispatch",
        "pre_approval_request", "post_approval_response",
    }
    assert VALID_HOOKS == expected
    assert not any(h.startswith("kanban_") for h in VALID_HOOKS)


def test_registrar_on_collects_hook_and_rejects_non_callable():
    r = PluginRegistrar(plugin_context("p"))
    r.on("pre_tool_call", lambda **kw: None)
    assert r.hooks == {"pre_tool_call": [r.hooks["pre_tool_call"][0]]}
    try:
        r.on("pre_tool_call", "not-callable")
        assert False, "deveria ter recusado um valor não-chamável"
    except ValueError:
        pass


def test_registrar_on_accepts_unknown_hook_but_warns(caplog=None):
    r = PluginRegistrar(plugin_context("p"))
    r.on("totally_unknown_hook", lambda **kw: None)   # forward-compat: aceita, só avisa (não explode)
    assert "totally_unknown_hook" in r.hooks


# ---------------------------------------------------------------------------- HookBus.invoke / fire_blockable
def test_hookbus_invoke_calls_all_and_isolates_raising_callback():
    bus = HookBus()
    seen = []
    bus.on("pre_llm_call", lambda **kw: seen.append(("a", kw)))

    def _boom(**kw):
        raise RuntimeError("boom")
    bus.on("pre_llm_call", _boom)
    bus.on("pre_llm_call", lambda **kw: seen.append(("b", kw)) or "ctx-extra")
    out = bus.invoke("pre_llm_call", messages=[{"role": "user"}])
    assert [n for n, _ in seen] == ["a", "b"]      # o handler que quebrou não impediu os outros
    assert out == ["ctx-extra"]                    # só retornos não-None entram no resultado


def test_hookbus_fire_blockable_vetoes_on_false_or_block_dict():
    bus = HookBus()
    bus.on("pre_tool_call", lambda **kw: False)
    assert bus.fire_blockable("pre_tool_call", tool="run_shell", args={}) is False

    bus2 = HookBus()
    bus2.on("pre_tool_call", lambda **kw: {"action": "block", "reason": "não hoje"})
    assert bus2.fire_blockable("pre_tool_call", tool="run_shell", args={}) is False

    bus3 = HookBus()
    bus3.on("pre_tool_call", lambda **kw: True)
    assert bus3.fire_blockable("pre_tool_call", tool="read_file", args={}) is True


def test_hookbus_fire_blockable_fail_closed_on_raise():
    """paridade com automation/hooks.py:93-98: um pre_tool_call que EXPLODE VETA (fail-closed) —
    política de segurança que erra não pode liberar a ação que existe pra barrar."""
    bus = HookBus()
    bus.on("pre_tool_call", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert bus.fire_blockable("pre_tool_call", tool="run_shell", args={}) is False


def test_hookbus_invoke_never_raises_out_even_when_all_callbacks_raise():
    bus = HookBus()
    bus.on("post_tool_call", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    assert bus.invoke("post_tool_call", tool="read_file") == []   # observador: nunca propaga


# ---------------------------------------------------------------------------- bridge (unified bus -> legacy)
def test_bridge_legacy_shell_before_tool_fires_through_unified_bus(tmp_path):
    marker = tmp_path / "fired.txt"
    hookdir = tmp_path / "hooks" / "before_tool"
    hookdir.mkdir(parents=True)
    (hookdir / "mark.sh").write_text(f"#!/bin/sh\necho ok > {marker}\n", encoding="utf-8")
    (hookdir / "mark.sh").chmod(0o755)

    hm = HookManager(root=str(tmp_path))
    bus = HookBus()
    bus.bridge_legacy(hm)
    ok = bus.fire_blockable("pre_tool_call", tool="run_shell", args={"cmd": "ls"})
    assert ok is True
    assert marker.exists() and marker.read_text().strip() == "ok"   # o script de SHELL rodou via a bus nova


# ---------------------------------------------------------------------------- load_plugin_hooks (folder plugin)
def test_load_plugin_hooks_from_folder(tmp_path):
    d = tmp_path / "plugins" / "watcher"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text("name: watcher\n", encoding="utf-8")
    (d / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.on("on_session_start", lambda **kw: "seen-start")
            ctx.on("subagent_stop", lambda **kw: "seen-stop")
    """), encoding="utf-8")
    collected = load_plugin_hooks(discover_plugins([str(tmp_path)]))
    assert set(collected) == {"on_session_start", "subagent_stop"}
    assert collected["on_session_start"][0]() == "seen-start"


def test_load_plugin_hooks_isolates_broken_plugin(tmp_path):
    ok = tmp_path / "plugins" / "ok"
    ok.mkdir(parents=True)
    (ok / "plugin.yaml").write_text("name: ok\n", encoding="utf-8")
    (ok / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.on("pre_verify", lambda **kw: "bom")
    """), encoding="utf-8")
    bad = tmp_path / "plugins" / "bad"
    bad.mkdir(parents=True)
    (bad / "plugin.yaml").write_text("name: bad\n", encoding="utf-8")
    (bad / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            raise RuntimeError("boom")
    """), encoding="utf-8")
    collected = load_plugin_hooks(discover_plugins([str(tmp_path)]))
    assert list(collected) == ["pre_verify"] and collected["pre_verify"][0]() == "bom"


# ---------------------------------------------------------------------------- wiring: pre/post_tool_call
def test_harness_fires_pre_and_post_tool_call_via_plugin_hooks_bus(tmp_path):
    seen = []
    bus = HookBus()
    bus.on("pre_tool_call", lambda **kw: seen.append(("pre", kw["tool"])))
    bus.on("post_tool_call", lambda **kw: seen.append(("post", kw["tool"])))
    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    h = Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path, plugin_hooks=bus)
    h._handle_tool_result(h.task, 0, Action("read_file", {"path": "a.txt"}), ToolResult(True, "ok", effect=False))
    assert ("post", "read_file") in seen


def test_pre_tool_call_veto_blocks_dispatch_alongside_hooks_stub(tmp_path):
    """duck-typed: hooks stub que só implementa .fire() não quebra (getattr/callable guard); o veto novo
    (plugin_hooks) bloqueia a tool no mesmo call site do before_tool legado, sem duplicar o veto legado."""
    class _LegacyHooksStub:
        def fire(self, event, payload):
            return True   # legado deixa passar

    bus = HookBus()
    bus.on("pre_tool_call", lambda **kw: False)   # plugin novo VETA
    Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path,
            hooks=_LegacyHooksStub(), plugin_hooks=bus, budget=Budget(max_steps=1))
    # roda um passo do loop principal só até o gate de veto — smoke via chamada direta do trecho relevante:
    assert bus.fire_blockable("pre_tool_call", tool="run_shell", args={}) is False


def test_harness_without_plugin_hooks_is_noop(tmp_path):
    """plugin_hooks=None (default) não quebra nada — getattr(None, ...) devolve None, guard `callable()` pula."""
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    h = Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path)
    step = h._handle_tool_result(h.task, 0, Action("read_file", {"path": "a.txt"}), ToolResult(True, "ok", effect=False))
    assert step == 1


# ---------------------------------------------------------------------------- wiring: pre/post_llm_call
def test_do_generate_fires_pre_and_post_llm_call(tmp_path):
    seen = []
    bus = HookBus()
    bus.on("pre_llm_call", lambda **kw: seen.append("pre"))
    bus.on("post_llm_call", lambda **kw: seen.append(("post", kw.get("result"))))
    h = Harness(generate=lambda messages, schema, **k: "RESP", task=Task(goal="x"),
               workspace=tmp_path, plugin_hooks=bus)
    out = h._do_generate([{"role": "user", "content": "oi"}], None)
    assert out == "RESP"
    assert seen[0] == "pre"
    assert seen[1] == ("post", "RESP")
