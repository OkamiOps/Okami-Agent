"""Wiring da pesquisa #7: as tools novas (audio_analyze, notify, todo_write) entram no
default_registry e são re-exportadas pela fachada okami.core.tools. Sem isto, as tools existem
mas o modelo nunca as vê (não estão no registro) — o registry é a ponte entre arquivo e harness."""

from __future__ import annotations


def test_default_registry_has_new_tools():
    from okami.core.tools.registry import default_registry
    reg = default_registry()
    for name in ("audio_analyze", "notify", "todo_write"):
        assert name in reg, f"{name} ausente do default_registry()"


def test_new_tools_have_correct_classes():
    from okami.core.tools.audio import AudioAnalyze
    from okami.core.tools.notify import Notify
    from okami.core.tools.todo import TodoWrite
    from okami.core.tools.registry import default_registry
    reg = default_registry()
    assert isinstance(reg["audio_analyze"], AudioAnalyze)
    assert isinstance(reg["notify"], Notify)
    assert isinstance(reg["todo_write"], TodoWrite)


def test_facade_reexports_new_tools():
    # quem faz `from okami.core.tools import AudioAnalyze/Notify/TodoWrite` continua funcionando
    import okami.core.tools as t
    assert hasattr(t, "AudioAnalyze") and hasattr(t, "Notify") and hasattr(t, "TodoWrite")
    assert "AudioAnalyze" in t.__all__
    assert "Notify" in t.__all__
    assert "TodoWrite" in t.__all__


def test_existing_tools_still_registered():
    # aditivo: as tools que já existiam continuam no registro (não quebrei nada ao adicionar)
    from okami.core.tools.registry import default_registry
    reg = default_registry()
    for name in ("respond", "read_file", "run_shell", "web_search", "task_complete"):
        assert name in reg
