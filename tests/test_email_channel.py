"""Item 19 — canal de e-mail (IMAP poll + SMTP send), stdlib (Gmail app-password).

Cobre: poll() parseia UNSEEN → Inbound (from/subject+corpo/Message-ID) com IMAP4_SSL mockado;
allowed() deny-by-default (allowlist de remetentes, espelha RestChannel); send() via smtplib mockado;
dedup por msg_id (Message-ID já visto não vira Inbound de novo).
"""

from __future__ import annotations

from email.message import EmailMessage


from okami.channels.email import EmailChannel


# ── fakes de imaplib / smtplib (sem rede) ──────────────────────────────────
def _raw(from_addr: str, subject: str, body: str, message_id: str) -> bytes:
    m = EmailMessage()
    m["From"] = from_addr
    m["Subject"] = subject
    m["Message-ID"] = message_id
    m.set_content(body)
    return m.as_bytes()


class _FakeIMAP:
    """Espelha o subconjunto de imaplib.IMAP4_SSL que o canal usa."""

    instances: list = []

    def __init__(self, host, port=993):
        self.host = host
        self.logged = None
        self.selected = None
        self.stored = []                  # (num, flags) marcados como lido
        self.logged_out = False
        # caixa: num -> raw bytes
        self.mailbox = {
            b"1": _raw("alice@example.com", "Oi", "corpo da alice", "<a@1>"),
            b"2": _raw("bob@example.com", "Tudo bem", "corpo do bob", "<b@2>"),
        }
        _FakeIMAP.instances.append(self)

    def login(self, user, pwd):
        self.logged = (user, pwd)
        return ("OK", [b"logged in"])

    def select(self, mailbox="INBOX"):
        self.selected = mailbox
        return ("OK", [b"2"])

    def search(self, charset, *criteria):
        return ("OK", [b" ".join(self.mailbox.keys())])

    def fetch(self, num, parts):
        n = num if isinstance(num, bytes) else str(num).encode()
        return ("OK", [(b"%s (RFC822 {n})" % n, self.mailbox[n])])

    def store(self, num, flags, value):
        self.stored.append((num, value))
        return ("OK", [b"stored"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b"logout"])


class _FakeSMTP:
    instances: list = []

    def __init__(self, host, port=465):
        self.host = host
        self.sent = []
        self.logged = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pwd):
        self.logged = (user, pwd)

    def send_message(self, msg):
        self.sent.append(msg)


def _patch(monkeypatch):
    _FakeIMAP.instances.clear()
    _FakeSMTP.instances.clear()
    import imaplib
    import smtplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)


# ── poll ───────────────────────────────────────────────────────────────────
def test_poll_parseia_unseen_para_inbound(monkeypatch):
    _patch(monkeypatch)
    ch = EmailChannel(user="me@gmail.com", app_password="apppw", allow_all=True)
    inb = ch.poll()
    assert len(inb) == 2
    a = inb[0]
    assert a.channel == "email"
    assert a.chat_id == "alice@example.com"
    assert "Oi" in a.text and "corpo da alice" in a.text   # assunto + corpo
    assert a.msg_id == "<a@1>"


def test_poll_marca_lido(monkeypatch):
    _patch(monkeypatch)
    ch = EmailChannel(user="me@gmail.com", app_password="pw", allow_all=True)
    ch.poll()
    imap = _FakeIMAP.instances[-1]
    assert imap.stored                                     # marcou \Seen
    assert all("Seen" in v for _, v in imap.stored)


def test_poll_dedup_por_msg_id(monkeypatch):
    _patch(monkeypatch)
    ch = EmailChannel(user="me@gmail.com", app_password="pw", allow_all=True)
    assert len(ch.poll()) == 2
    # segunda rodada: mesmos Message-ID já vistos → nada novo
    assert ch.poll() == []


# ── allowed (deny-by-default) ──────────────────────────────────────────────
def test_allowed_deny_by_default():
    ch = EmailChannel(user="me@gmail.com", app_password="pw",
                      allow_chats=["alice@example.com"])
    assert ch.allowed("alice@example.com") is True
    assert ch.allowed("Alice@Example.COM") is True         # case-insensitive
    assert ch.allowed("stranger@evil.com") is False        # fora da allowlist → deny


def test_allowed_sem_allowlist_nem_allowall_nega():
    ch = EmailChannel(user="me@gmail.com", app_password="pw")
    assert ch.allowed("qualquer@x.com") is False           # deny-by-default


# ── send ───────────────────────────────────────────────────────────────────
def test_send_via_smtp(monkeypatch):
    _patch(monkeypatch)
    ch = EmailChannel(user="me@gmail.com", app_password="pw", allow_all=True)
    ch.send("dest@example.com", "minha resposta")
    smtp = _FakeSMTP.instances[-1]
    assert smtp.logged == ("me@gmail.com", "pw")
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["To"] == "dest@example.com"
    assert msg["From"] == "me@gmail.com"
    assert "minha resposta" in msg.get_content()


def test_poll_interval_existe():
    ch = EmailChannel(user="x@gmail.com", app_password="pw")
    assert isinstance(ch.poll_interval, (int, float))
    assert ch.poll_interval > 0
