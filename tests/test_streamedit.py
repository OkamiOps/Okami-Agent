"""Streaming-by-edit (paridade OpenClaw draft-stream): uma ÚNICA mensagem de status é EDITADA ao vivo
com o progresso (tool-calls), em vez de inundar o chat com linhas soltas. StreamEditor coalesce +
throttle (não spamma editMessage → evita 429). Telegram ganha edit_message; canal sem suporte = no-op."""

from __future__ import annotations

from okami.gateway.streamedit import StreamEditor


# ----------------------------------------------------------------- StreamEditor (throttle + render)
def test_first_feed_is_due():
    ed = StreamEditor(min_interval=1.0)
    ed.feed("📖 read_file", now=100.0)
    assert ed.due(now=100.0)                               # 1ª atualização sai na hora


def test_throttled_within_interval():
    ed = StreamEditor(min_interval=1.0, adaptive=False)    # contrato do throttle FIXO (adaptativo tem teste próprio)
    ed.feed("a", now=100.0)
    ed.mark_sent(now=100.0)
    ed.feed("b", now=100.5)
    assert not ed.due(now=100.5)                           # <1s desde o último envio → segura
    assert ed.due(now=101.1)                               # passou o intervalo → libera


def test_render_keeps_recent_lines():
    ed = StreamEditor(min_interval=0, keep=3)
    for i in range(5):
        ed.feed(f"linha {i}", now=float(i))
    out = ed.render()
    assert "linha 4" in out and "linha 2" in out and "linha 0" not in out   # só as 3 últimas


def test_render_has_header():
    ed = StreamEditor(min_interval=0, header="💭 trabalhando")
    ed.feed("📖 read_file", now=0.0)
    assert ed.render().startswith("💭 trabalhando")


def test_dedup_consecutive_identical():
    ed = StreamEditor(min_interval=0, keep=5)
    ed.feed("📖 read_file", now=0.0)
    ed.feed("📖 read_file", now=1.0)                       # idêntica seguida → não duplica
    assert ed.render().count("📖 read_file") == 1


# ----------------------------------------------------------------- Telegram edit_message
def test_telegram_edit_message_calls_api(monkeypatch):
    from okami.channels.telegram import TelegramClient
    cap = {}
    monkeypatch.setattr(TelegramClient, "_call",
                        lambda self, m, p, **k: (cap.update(method=m, params=p), {"ok": True})[1])
    c = TelegramClient("tok")
    c.edit_message("9", 123, "novo texto **forte**")
    assert cap["method"] == "editMessageText"
    assert cap["params"]["message_id"] == 123 and cap["params"]["chat_id"] == "9"


def test_telegram_send_status_returns_msg_id(monkeypatch):
    from okami.channels.telegram import TelegramChannel
    ch = TelegramChannel("tok")
    monkeypatch.setattr(ch.client, "_call",
                        lambda m, p, **k: {"ok": True, "result": {"message_id": 555}})
    assert ch.send_status("9", "💭 pensando…") == 555


def test_base_channel_edit_is_noop_false():
    from okami.channels.base import Channel
    assert Channel().supports_edit is False
    assert Channel().edit_message("9", 1, "x") is False


# ----------------------------------------------------------------- integração no gateway
def test_run_edits_status_live_then_into_reply():
    import tempfile
    from okami.channels.base import Channel
    from okami.core import Task, TaskState
    from okami.gateway import AgentEndpoint

    class EditCh(Channel):
        name = "telegram"
        supports_edit = True
        def __init__(self):
            self.sent: list = []
            self.edits: list = []
            self._next = 1
        def poll(self):
            return []
        def send(self, chat_id, text):
            self.sent.append(text)
        def send_status(self, chat_id, text):
            self.edits.append(("send", text))
            self._next += 1
            return self._next
        def edit_message(self, chat_id, mid, text):
            self.edits.append(("edit", text))
            return True
        def allowed(self, c):
            return True

    def runner(cfg, ws, goal, *, on_event=None, **kw):
        if on_event:
            on_event({"kind": "step", "tool": "read_file", "ok": True, "args": {"path": "a.py"}})
            on_event({"kind": "step", "tool": "run_shell", "ok": True, "args": {"cmd": "ls"}})
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "resposta final curta"
        return t

    ch = EditCh()
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                       spawn=lambda fn: fn())
    ep.handle("7", "faz algo")
    # houve pelo menos um envio de status + edições ao vivo; a resposta final aparece (edição ou send)
    assert any(k == "send" for k, _ in ch.edits)
    allcontent = " ".join(t for _, t in ch.edits) + " ".join(ch.sent)
    assert "resposta final curta" in allcontent
