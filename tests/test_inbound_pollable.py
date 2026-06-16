"""#20 inbound dos canais pollable — Signal, Matrix, BlueBubbles. Parsers puros + poll() com _get mockável."""
from __future__ import annotations


# ── parsers puros (payload da API → Inbound) ──
def test_parse_signal_receive():
    from okami.channels.inbound_parsers import parse_signal_receive
    payload = [
        {"envelope": {"source": "+15551112222", "timestamp": 111,
                      "dataMessage": {"message": "olá bot"}}},
        {"envelope": {"source": "+15551112222", "timestamp": 112, "dataMessage": {"message": ""}}},  # vazio → skip
        {"envelope": {"source": "+1SELF", "timestamp": 113,
                      "dataMessage": {"message": "eco do bot"}}},                                     # self → skip
    ]
    out = parse_signal_receive(payload, self_number="+1SELF")
    assert len(out) == 1
    assert out[0].text == "olá bot" and out[0].chat_id == "+15551112222" and out[0].msg_id == "111"


def test_parse_matrix_sync():
    from okami.channels.inbound_parsers import parse_matrix_sync
    payload = {
        "next_batch": "s2_token",
        "rooms": {"join": {"!room:hs": {"timeline": {"events": [
            {"type": "m.room.message", "event_id": "$e1", "sender": "@user:hs",
             "content": {"msgtype": "m.text", "body": "oi matrix"}},
            {"type": "m.room.message", "event_id": "$e2", "sender": "@bot:hs",
             "content": {"msgtype": "m.text", "body": "eco"}},                   # self → skip
            {"type": "m.room.member", "sender": "@user:hs", "content": {}},      # não-mensagem → skip
        ]}}}},
    }
    msgs, nxt = parse_matrix_sync(payload, self_user="@bot:hs")
    assert nxt == "s2_token" and len(msgs) == 1
    assert msgs[0].text == "oi matrix" and msgs[0].chat_id == "!room:hs" and msgs[0].msg_id == "$e1"


def test_parse_bluebubbles():
    from okami.channels.inbound_parsers import parse_bluebubbles
    payload = {"data": [
        {"guid": "g1", "text": "oi imessage", "isFromMe": False, "handle": {"address": "+15550000"}},
        {"guid": "g2", "text": "minha resposta", "isFromMe": True, "handle": {"address": "+15550000"}},  # self → skip
    ]}
    out = parse_bluebubbles(payload)
    assert len(out) == 1 and out[0].text == "oi imessage" and out[0].msg_id == "g1"


# ── poll() dos canais (delega ao parser; _get mockável) ──
def test_signal_channel_poll(monkeypatch):
    from okami.channels.messaging import SignalChannel
    ch = SignalChannel("http://localhost:8080", "+1SELF", "+1SELF")
    ch._get = lambda path, params=None: [{"envelope": {"source": "+1OTHER", "timestamp": 9,
                                                        "dataMessage": {"message": "ping"}}}]
    msgs = ch.poll()
    assert len(msgs) == 1 and msgs[0].text == "ping"


def test_matrix_channel_poll_advances_token(monkeypatch):
    from okami.channels.messaging import MatrixChannel
    ch = MatrixChannel("https://hs", "tok", "!r:hs")
    seen = {}

    def _get(path, params=None):
        seen["since"] = (params or {}).get("since")
        return {"next_batch": "NEXT", "rooms": {"join": {"!r:hs": {"timeline": {"events": [
            {"type": "m.room.message", "event_id": "$x", "sender": "@u:hs",
             "content": {"msgtype": "m.text", "body": "hey"}}]}}}}}

    ch._get = _get
    msgs = ch.poll()
    assert len(msgs) == 1 and msgs[0].text == "hey"
    ch.poll()                                              # 2ª chamada usa o token avançado
    assert seen["since"] == "NEXT"


def test_bluebubbles_channel_poll(monkeypatch):
    from okami.channels.messaging import BlueBubblesChannel
    ch = BlueBubblesChannel("http://localhost:1234", "pw", "chatguid")
    ch._get = lambda path, params=None: {"data": []}       # server vazio → start() prima (baseline vazio)
    ch.start()
    ch._get = lambda path, params=None: {"data": [
        {"guid": "g9", "text": "yo", "isFromMe": False, "handle": {"address": "x"}}]}
    msgs = ch.poll()
    assert len(msgs) == 1 and msgs[0].text == "yo"         # mensagem NOVA após baseline é emitida


def test_bluebubbles_first_poll_baselines_when_prime_failed(monkeypatch):
    """#20 bug-hunt [8]: se start() falhou (server offline no boot), o 1º poll bem-sucedido NÃO pode
    despejar o backlog inteiro (até 50 msgs antigas) como 'novas' — ele baseliza e não emite nada."""
    from okami.channels.messaging import BlueBubblesChannel
    ch = BlueBubblesChannel("http://x", "pw", "g")          # start() NUNCA rodou com sucesso → _seen vazio
    ch._get = lambda path, params=None: {"data": [
        {"guid": f"g{i}", "text": f"m{i}", "isFromMe": False, "handle": {"address": "a"}} for i in range(40)]}
    assert ch.poll() == []                                  # 1º poll = baseline tardio (sem flood)
    ch._get = lambda path, params=None: {"data": [
        {"guid": "gNEW", "text": "nova", "isFromMe": False, "handle": {"address": "a"}}]}
    out = ch.poll()
    assert len(out) == 1 and out[0].msg_id == "gNEW"        # só a mensagem realmente nova depois


def test_bluebubbles_lru_keeps_newest(monkeypatch):
    """#20 bug-hunt [4]: a poda do _seen deve manter os guids MAIS RECENTES (ordem de inserção), não um
    subconjunto arbitrário de um set — senão um guid recém-visto é re-emitido como novo."""
    from okami.channels.messaging import BlueBubblesChannel
    ch = BlueBubblesChannel("http://x", "pw", "g")
    ch.start()                                              # primed
    # injeta 2500 guids antigos em ordem; o último visto deve sobreviver à poda
    seq = [{"guid": f"old{i}", "text": "x", "isFromMe": False, "handle": {"address": "a"}} for i in range(2500)]
    ch._get = lambda path, params=None: {"data": seq}
    ch.poll()
    recent = f"old{2499}"
    assert recent in ch._seen                               # o mais recente NÃO foi evictado
    # re-ver o guid mais recente não o re-emite (continua deduplicado)
    ch._get = lambda path, params=None: {"data": [
        {"guid": recent, "text": "x", "isFromMe": False, "handle": {"address": "a"}}]}
    assert ch.poll() == []


# ── parsers de webhook-push (callback → Inbound) ──
def test_parse_dingtalk_webhook():
    from okami.channels.inbound_parsers import parse_dingtalk_webhook
    inb = parse_dingtalk_webhook({"msgtype": "text", "text": {"content": "oi dt"},
                                  "conversationId": "c1", "msgId": "m1"})
    assert inb and inb.channel == "dingtalk" and inb.chat_id == "c1" and inb.text == "oi dt"
    assert parse_dingtalk_webhook({"msgtype": "image"}) is None


def test_parse_wecom_and_weixin_webhook():
    from okami.channels.inbound_parsers import parse_wecom_webhook, parse_weixin_webhook
    xml = "<xml><MsgType>text</MsgType><Content><![CDATA[oi wc]]></Content><FromUserName>u1</FromUserName><MsgId>9</MsgId></xml>"
    wc = parse_wecom_webhook(xml)
    assert wc and wc.channel == "wecom" and wc.chat_id == "u1" and wc.text == "oi wc"
    wx = parse_weixin_webhook(xml)
    assert wx and wx.channel == "weixin" and wx.text == "oi wc"


def test_parse_qqbot_webhook():
    from okami.channels.inbound_parsers import parse_qqbot_webhook
    inb = parse_qqbot_webhook({"id": "1", "content": "oi qq", "channel_id": "ch9", "author": {"id": "a"}})
    assert inb and inb.channel == "qqbot" and inb.chat_id == "ch9" and inb.text == "oi qq"


def test_parse_whatsapp_webhook():
    from okami.channels.inbound_parsers import parse_whatsapp_webhook
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid1", "type": "text", "text": {"body": "oi wa"}, "from": "+5511"}]}}]}]}
    inb = parse_whatsapp_webhook(body)
    assert inb and inb.channel == "whatsapp" and inb.chat_id == "+5511" and inb.text == "oi wa"


def test_parse_sms_webhook():
    from okami.channels.inbound_parsers import parse_sms_webhook
    inb = parse_sms_webhook({"From": "+1", "To": "+2", "Body": "oi sms", "MessageSid": "SM1"})
    assert inb and inb.channel == "sms" and inb.chat_id == "+1" and inb.text == "oi sms"


# ── wiring: WebhookRoute.parser entrega a MENSAGEM real ao agente ──
def test_webhook_route_parser_delivers_parsed_text():
    import json

    from okami.channels.inbound_parsers import webhook_parser
    from okami.channels.webhook import WebhookRoute, WebhookServer
    from okami.channels.webhook_sig import _digest
    got = {}
    route = WebhookRoute(provider="generic", secret="s", parser=webhook_parser("dingtalk"))
    srv = WebhookServer(routes={"/wh/dt": route},
                        handle=lambda text, r: got.update({"text": text, "chat": r.chat_id}))
    body = json.dumps({"msgtype": "text", "text": {"content": "oi via webhook"},
                       "conversationId": "c1"}).encode("utf-8")
    status, _ = srv.handle_post("/wh/dt", {"X-Signature": _digest("s", body)}, body)
    assert status == 200 and got["text"] == "oi via webhook" and got["chat"] == "c1"


def test_webhook_route_parser_ignores_non_text():
    import json

    from okami.channels.inbound_parsers import webhook_parser
    from okami.channels.webhook import WebhookRoute, WebhookServer
    from okami.channels.webhook_sig import _digest
    called = []
    route = WebhookRoute(provider="generic", secret="s", parser=webhook_parser("dingtalk"))
    srv = WebhookServer(routes={"/wh/dt": route}, handle=lambda text, r: called.append(text))
    body = json.dumps({"msgtype": "image"}).encode("utf-8")     # não-texto
    status, _ = srv.handle_post("/wh/dt", {"X-Signature": _digest("s", body)}, body)
    assert status == 200 and not called                          # ignorado, agente não roda


# ── #20 bug-hunt: correções confirmadas (≥2/3 céticos) ──
def test_dingtalk_text_as_string_does_not_crash():
    """[2]: payload malformado com text=str (não dict) não pode lançar AttributeError — vira None."""
    from okami.channels.inbound_parsers import parse_dingtalk_webhook
    assert parse_dingtalk_webhook({"msgtype": "text", "text": "raw string"}) is None
    # forma correta segue funcionando
    ok = parse_dingtalk_webhook({"msgtype": "text", "text": {"content": "oi"}, "conversationId": "c"})
    assert ok and ok.text == "oi"


def test_wecom_xml_decodes_entities():
    """[1]: entidades XML no Content devem ser DECODIFICADAS (&lt;→<, &amp;→&), não entregues literais."""
    from okami.channels.inbound_parsers import parse_wecom_webhook
    xml = ("<xml><MsgType>text</MsgType><Content>5 &lt; 10 &amp; ok</Content>"
           "<FromUserName>u1</FromUserName></xml>")
    inb = parse_wecom_webhook(xml)
    assert inb and inb.text == "5 < 10 & ok"


def test_webhook_parser_does_not_mutate_shared_route():
    """[5]: handle_post NÃO pode mutar route.chat_id (objeto compartilhado entre POSTs paralelos) — o
    handler recebe o chat certo via cópia, mas a rota original fica intacta (sem corrida de roteamento)."""
    import json

    from okami.channels.inbound_parsers import webhook_parser
    from okami.channels.webhook import WebhookRoute, WebhookServer
    from okami.channels.webhook_sig import _digest
    seen = []
    route = WebhookRoute(provider="generic", secret="s", chat_id="DEFAULT", parser=webhook_parser("dingtalk"))
    srv = WebhookServer(routes={"/wh": route}, handle=lambda text, r: seen.append(r.chat_id))
    body = json.dumps({"msgtype": "text", "text": {"content": "oi"}, "conversationId": "alice"}).encode("utf-8")
    srv.handle_post("/wh", {"X-Signature": _digest("s", body)}, body)
    assert seen == ["alice"]                                # handler roteou p/ o remetente certo
    assert route.chat_id == "DEFAULT"                       # rota COMPARTILHADA não foi mutada
