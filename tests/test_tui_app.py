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


def test_tui_slash_shows_navigable_command_menu(tmp_path):
    # digitar '/mo' mostra o MENU navegável (/model /models /mouse); Enter completa o destacado; texto some.
    out = {}

    async def scenario():
        from textual.widgets import Input, OptionList
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            menu = app.query_one("#cmdmenu", OptionList)
            app.on_input_changed(type("E", (), {"value": "/mo"})())    # digitou /mo → menu aparece
            out["shown"] = menu.display
            out["count"] = menu.option_count
            out["ids"] = [menu.get_option_at_index(i).id for i in range(menu.option_count)]
            # Enter com o menu aberto → COMPLETA o input com o destacado (não envia)
            handled = app._accept_highlighted()
            out["completed"] = app.query_one("#input", Input).value
            out["handled"] = handled
            out["hidden_after"] = menu.display
            app.on_input_changed(type("E", (), {"value": "oi"})())     # texto normal → some
            out["hidden"] = menu.display

    asyncio.run(scenario())
    assert out["shown"] is True and out["count"] >= 3
    assert {"model", "models", "mouse"} <= set(out["ids"])
    assert out["handled"] is True and out["completed"] == "/model "    # completou o 1º destacado
    assert out["hidden_after"] is False and out["hidden"] is False


def test_command_matches_filters_and_ignores_args():
    from okami import commands as _cmds
    from okami import tui
    ids = [name for _, name in tui.command_matches("/mo")]
    assert {"model", "models", "mouse"} <= set(ids)
    assert tui.command_matches("/model x") == []      # já nos args → não sugere
    assert tui.command_matches("oi") == []            # não é comando
    # '/' lista TODOS os comandos de chat (não só os 12 primeiros) — o usuário não decora os nomes
    all_ids = {name for _, name in tui.command_matches("/")}
    chat = {c.name for c in _cmds.COMMAND_REGISTRY if c.scope in ("chat", "both")}
    assert all_ids == chat and "model" in all_ids


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


def test_copy_command_routes():
    from okami import tui
    assert tui._route_repl_line("/copy", busy=False, pending_approval=False) == "copy"
    assert tui._route_repl_line("/copy all", busy=False, pending_approval=False) == "copy"
    # /copy é comando de chat (autocomplete) e tem alias /yank
    from okami import commands as _cmds
    assert _cmds.resolve("/copy") is not None and _cmds.resolve("/yank").name == "copy"


def test_cmd_copy_puts_last_reply_on_clipboard(tmp_path):
    # /copy copia a ÚLTIMA resposta da agente (sem precisar selecionar) — resolve o "não consigo copiar".
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            copied = {}
            app.copy_to_clipboard = lambda txt: copied.setdefault("txt", txt)
            app.transcript.extend([("user", "oi"), ("agent", "primeira"), ("user", "e ai"),
                                   ("agent", "RELATÓRIO: bug X em base.py:31")])
            app._cmd_copy("/copy")
            out["last"] = copied.get("txt")
            copied.clear()
            app._cmd_copy("/copy all")
            out["all"] = copied.get("txt")
            out["notes"] = [v for k, v in app.transcript if k == "note"]

    asyncio.run(scenario())
    assert out["last"] == "RELATÓRIO: bug X em base.py:31"            # só a última resposta
    assert "primeira" in out["all"] and "RELATÓRIO" in out["all"] and "você: oi" in out["all"]  # conversa inteira


def test_mouse_on_by_default(tmp_path):
    # default: mouse ON (clica autocomplete/botões) E a seleção do Textual funciona junto. Sem trocar off/on.
    app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                       run_task=_fake_runner, spawn=lambda fn: fn())
    assert app._mouse_on is True
    assert not hasattr(app, "on_mouse_up")                    # NÃO limpa a seleção ao soltar (era o "bloqueio")


def test_ctrl_c_copies_the_textual_selection(tmp_path):
    # arrastou pra selecionar (Textual marca) → ^C copia a seleção pro clipboard (a seleção FICA até copiar).
    import asyncio

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            copied = {}
            app.copy_to_clipboard = lambda t: copied.setdefault("txt", t)
            app.screen.get_selected_text = lambda: "TEXTO SELECIONADO ABC"   # simula a seleção do Textual
            app.clear_selection = lambda: None
            app.action_ctrl_c()                              # ^C com seleção → copia (não cancela)
            return copied.get("txt")

    assert "TEXTO SELECIONADO" in (asyncio.run(scenario()) or "")
