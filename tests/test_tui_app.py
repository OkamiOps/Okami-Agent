"""TUI de tela cheia (Textual): render de mensagem, roundtrip, status/gauge, aprovação por botão.

Usa o test-harness do Textual (`App.run_test()` + Pilot) embrulhado em asyncio.run (sem pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import queue as _queue

from okami.core import Task, TaskState
from okami.tui_app import OkamiChatApp, _HAS_TEXTUAL, _render_message, run_chat_tui


def _fake_runner(cfg, ws, goal, **kw):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"eco: {goal}"
    return t


def test_textual_available_and_app_class():
    assert _HAS_TEXTUAL and OkamiChatApp is not None and callable(run_chat_tui)


def test_render_message_markdown_vs_text():
    from rich.markdown import Markdown
    from rich.text import Text
    assert isinstance(_render_message("✅ feito\n```\nx=1\n```"), Markdown)   # fala c/ código → Markdown
    assert isinstance(_render_message("oi tudo bem"), Markdown)               # fala simples → Markdown
    assert isinstance(_render_message("💭 pensando…"), Text)                  # sistema → Text colorido


def test_status_text_has_model_gauge_and_ready_state(tmp_path):
    app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                       run_task=_fake_runner, model_label="codex/gpt-5.5", spawn=lambda fn: fn())
    plain = app._status_text().plain
    assert "codex/gpt-5.5" in plain and "pronto" in plain and "ctx" in plain and "trocas" in plain


def test_tui_renders_command_output_with_brain_emoji(tmp_path):
    # REGRESSÃO: /model responde "🧠 modelo: …" e o TUI NÃO pode engolir. Só o 💭 ("pensando") some.
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.sink_message("terminal", "🧠 modelo: MiniMax-M3 · /models lista")
            app.sink_message("terminal", "💭 okami está pensando…")
            await pilot.pause()
            out["t"] = list(app.transcript)

    asyncio.run(scenario())
    notes = [v for k, v in out["t"] if k == "note"]
    assert any("modelo: MiniMax-M3" in n for n in notes), "/model foi engolido"
    assert not any("pensando" in n for n in notes), "💭 não foi escondido"


def test_ctrl_c_copies_selection_to_clipboard(tmp_path):
    # Copiar texto no CLI: com seleção (arraste do mouse), ^C copia (mouse segue ligado).
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.get_selected_text = lambda: "trecho selecionado pra copiar"   # simula seleção
            copied = {}
            app.copy_to_clipboard = lambda txt: copied.setdefault("txt", txt)
            app.action_ctrl_c()
            await pilot.pause()
            out["copied"] = copied.get("txt")
            out["notes"] = [v for k, v in app.transcript if k == "note"]

    asyncio.run(scenario())
    assert out["copied"] == "trecho selecionado pra copiar"
    assert any("copiado" in n for n in out["notes"])


def test_tui_roundtrip_user_and_agent_appear(tmp_path):
    out = {}

    async def scenario():
        from textual.widgets import Input
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#input", Input).value = "oi"
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.05)
                if any(k == "agent" for k, _ in app.transcript):
                    break
            out["t"] = list(app.transcript)

    asyncio.run(scenario())
    t = out["t"]
    assert ("user", "oi") in t
    assert any(k == "agent" and "eco: oi" in v for k, v in t)


def test_tui_approval_bar_shows_and_button_answers(tmp_path):
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.ep._pending["terminal"] = _queue.Queue()      # simula go/no-go pendente
            await pilot.pause(0.3)                              # deixa o _tick mostrar a barra
            out["bar_shown"] = bool(app.query_one("#approval").display)
            await pilot.click("#approve")                       # botão Aprovar
            for _ in range(20):
                await pilot.pause(0.05)
                try:
                    out["answer"] = app.ep._pending["terminal"].get_nowait()
                    break
                except _queue.Empty:
                    continue

    asyncio.run(scenario())
    assert out.get("bar_shown") is True
    assert out.get("answer") == "/yes"                          # clicar Aprovar respondeu a aprovação


def test_tui_send_approval_opens_panel_with_action(tmp_path):
    """send_approval → o PAINEL abre na hora com a AÇÃO (não fica só texto '/yes ou /no' no log)."""
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#approval").display is False    # fechado de início
            app.ep._pending["terminal"] = _queue.Queue()          # fluxo real: _approve seta pending…
            app.show_approval("⚠ Aprovar [run_shell] · cmd=rm -rf / (risco=critical)")   # …e chama send_approval
            await pilot.pause(0.2)
            out["shown"] = bool(app.query_one("#approval").display)
            out["label"] = app._approval_text

    asyncio.run(scenario())
    assert out.get("shown") is True
    assert "run_shell" in out["label"] and "rm -rf" in out["label"]   # mostra a ação real


def test_tui_channel_has_send_approval():
    from okami.tui_app import TuiChannel
    assert hasattr(TuiChannel, "send_approval")     # o canal expõe o caminho de painel (não cai no texto)
