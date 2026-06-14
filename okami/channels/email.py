"""Canal de e-mail (item 19) — IMAP poll de UNSEEN + SMTP send, tudo stdlib (sem API paga).

Pensado p/ Gmail com app-password (imaplib.IMAP4_SSL / smtplib.SMTP_SSL), mas funciona com
qualquer provedor IMAP+SMTP sobre SSL. Mesma interface Channel (poll/send/allowed):
- poll(): busca UNSEEN, vira cada msg em Inbound("email", from_addr, text=assunto+corpo,
  msg_id=Message-ID), marca \\Seen e DEDUPa por Message-ID (não reprocessa o mesmo e-mail).
- send(): monta um EmailMessage e envia via SMTP.
- allowed(): allowlist de remetentes DENY-BY-DEFAULT (espelha RestChannel) — só quem está na
  lista (ou allow_all) fala com o agente. E-mail é superfície aberta: deny-by-default é a guarda.
"""

from __future__ import annotations

from okami.channels.base import Channel, Inbound

# limite defensivo de corpo: e-mail pode ser enorme; o gateway/LLM não precisa do anexo inteiro.
_BODY_LIMIT = 8000
_SEEN_MAX = 2000          # teto do dedup em memória (gateway de vida longa não vaza memória sem fim)


def _addr_only(raw: str) -> str:
    """Extrai só o endereço de um 'Nome <a@b.com>' e normaliza p/ minúsculo."""
    from email.utils import parseaddr
    addr = parseaddr(str(raw or ""))[1]
    return (addr or str(raw or "")).strip().lower()


def _auth_failed(msg) -> bool:
    """True se o provedor receptor MARCOU spoof: Authentication-Results com spf/dkim/dmarc=fail.
    O header From é forjável; só o Authentication-Results (posto pelo provedor, ex. Gmail) tem valor.
    Ausente → não dá p/ afirmar fail (não barra aqui; o corpo já entra como NÃO-confiável de qualquer jeito)."""
    ar = " ".join(str(v) for v in (msg.get_all("Authentication-Results") or [])).lower()
    return "spf=fail" in ar or "spf=softfail" in ar or "dkim=fail" in ar or "dmarc=fail" in ar


def _body_text(msg) -> str:
    """Extrai o corpo text/plain (ou cai pro payload bruto), decodificado e truncado."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    txt = part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    txt = payload.decode("utf-8", "replace")
                return txt[:_BODY_LIMIT]
        return ""
    try:
        txt = msg.get_content()
    except Exception:
        payload = msg.get_payload(decode=True) or b""
        txt = payload.decode("utf-8", "replace")
    return (txt or "")[:_BODY_LIMIT]


class EmailChannel(Channel):
    name = "email"

    def __init__(self, *, user: str, app_password: str,
                 imap_host: str = "imap.gmail.com", imap_port: int = 993,
                 smtp_host: str = "smtp.gmail.com", smtp_port: int = 465,
                 mailbox: str = "INBOX",
                 allow_chats=None, allow_all: bool = False,
                 poll_interval: float = 30.0):
        self.user = user
        self.app_password = app_password
        self.imap_host = imap_host
        self.imap_port = int(imap_port)
        self.smtp_host = smtp_host
        self.smtp_port = int(smtp_port)
        self.mailbox = mailbox
        # allowlist normalizada p/ minúsculo (e-mail é case-insensitive no endereço)
        self.allow = {str(a).strip().lower() for a in (allow_chats or [])}
        self.allow_all = bool(allow_all)
        self.poll_interval = float(poll_interval)   # IMAP não é push → loop do gateway espera isto
        from collections import OrderedDict
        self._seen: OrderedDict[str, None] = OrderedDict()  # dedup FIFO limitado (anti-leak de memória)

    def _mark_seen(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > _SEEN_MAX:          # evicta o mais antigo (bounded, não vaza memória)
            self._seen.popitem(last=False)

    def allowed(self, chat_id) -> bool:
        addr = str(chat_id).strip().lower()
        if self.allow:
            return addr in self.allow
        return self.allow_all                       # deny-by-default (igual ao RestChannel)

    def poll(self) -> list[Inbound]:
        import email as _email
        import imaplib

        out: list[Inbound] = []
        imap = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        try:
            imap.login(self.user, self.app_password)
            imap.select(self.mailbox)
            typ, data = imap.search(None, "UNSEEN")
            if typ != "OK":
                return out
            nums = (data[0] or b"").split() if data else []
            for num in nums:
                typ, msg_data = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue
                raw = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw = part[1]
                        break
                if raw is None:
                    continue
                msg = _email.message_from_bytes(raw)
                mid = str(msg.get("Message-ID") or "").strip()
                from_addr = _addr_only(msg.get("From", ""))
                subject = str(msg.get("Subject") or "").strip()
                body = _body_text(msg)
                # chave de dedup: Message-ID (do remetente) OU, se ausente/forjável, hash do conteúdo —
                # assim e-mail sem Message-ID também deduplica e não fica re-processando.
                import hashlib
                key = mid or "sha:" + hashlib.sha256(f"{from_addr}|{subject}|{body}".encode()).hexdigest()
                if key in self._seen:
                    continue                            # dedup: mesmo e-mail já virou turno
                self._mark_seen(key)
                imap.store(num, "+FLAGS", "\\Seen")     # marca lido (não relê na próxima rodada)
                if _auth_failed(msg):                   # provedor marcou spoof (spf/dkim/dmarc=fail) → ignora
                    continue
                # corpo de e-mail é atacante-controlável (From forjável) → entra como DADO não-confiável,
                # nunca como instrução pura de usuário (defesa contra injeção de prompt por e-mail).
                from okami.core.tools.base import untrusted_wrap
                raw_text = f"{subject}\n\n{body}".strip() if subject else body
                text = untrusted_wrap(f"email de {from_addr}", raw_text)
                out.append(Inbound("email", from_addr, text=text, msg_id=mid))
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return out

    def send(self, chat_id, text: str) -> None:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = self.user
        msg["To"] = str(chat_id)
        msg["Subject"] = "Okami"
        msg.set_content(text or "")
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as smtp:
            smtp.login(self.user, self.app_password)
            smtp.send_message(msg)
