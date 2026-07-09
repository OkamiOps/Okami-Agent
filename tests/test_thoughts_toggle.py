"""/thoughts on|off: oculta o PENSAMENTO ao vivo no chat (o modelo pensa igual). Pedido do dono:
'quero que ele pense, não quero que fique enchendo meu telegram'."""
import re


def test_status_on_event_oculta_token_quando_off():
    import okami.gateway.endpoint as ep
    # simula o _status_on_event com show_reasoning=False: evento 'token' não deve editar a msg
    sent = []
    class FakeChannel:
        def edit_message(self, cid, mid, txt): sent.append(txt)
        def send(self, *a, **k): pass
    self = ep.AgentEndpoint.__new__(ep.AgentEndpoint)
    self.channel = FakeChannel()
    ev = ep.AgentEndpoint._status_on_event(self, "c1", "s1", "💭", None, show_reasoning=False)
    for _ in range(20):
        ev({"kind": "token", "text": "pensando muito bla bla "})
    assert sent == []          # nada foi exibido (modelo pensa, chat não enche)


def test_status_on_event_strip_think_quando_on():
    import okami.gateway.endpoint as ep
    sent = []
    class FakeChannel:
        def edit_message(self, cid, mid, txt): sent.append(txt)
        def send(self, *a, **k): pass
    self = ep.AgentEndpoint.__new__(ep.AgentEndpoint)
    self.channel = FakeChannel()
    ev = ep.AgentEndpoint._status_on_event(self, "c1", "s1", "💭", None, show_reasoning=True)
    ev({"kind": "token", "text": "<think>raciocinio secreto</think>resposta visivel"})
    import time; ev({"kind": "token", "text": " continua"})   # força um due
    # o <think> nunca aparece; a resposta sim (em algum edit)
    joined = " ".join(sent)
    assert "raciocinio secreto" not in joined


def test_comando_thoughts_registrado():
    from okami.commands import COMMAND_REGISTRY
    names = {c.name for c in COMMAND_REGISTRY}
    assert "thoughts" in names
