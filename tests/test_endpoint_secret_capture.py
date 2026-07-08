"""Captura de credencial INLINE no gateway (okami/gateway/endpoint.py `_capture_inline_secrets`) —
diretivas do dono (BINDING):
  - "Salvar, apagar e confirmar": detecta, guarda no cofre, apaga a mensagem original (deleteMessage),
    redige do transcript/histórico/log, confirma só pelo NOME.
  - "Só no cofre, nunca no LLM": o valor cru NUNCA entra no contexto do modelo — detecção acontece
    ANTES de `_append_turn`/`run_task`; o modelo só vê uma nota saneada.

Também cobre o fix de ORDEM da redação de saída (redige ANTES de persistir no transcript, não depois).
"""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.core import secretvault as sv
from okami.gateway import AgentEndpoint

_TOKEN = "ghp_abcdef0123456789ABCDEF0123456789"  # pragma: allowlist secret


class FakeChannel(Channel):
    name = "fake"
    supports_media = False

    def __init__(self, allow_chats=None):
        self.sent: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.allow = {str(c) for c in (allow_chats or [])}

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return not self.allow or str(chat_id) in self.allow

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((str(chat_id), str(msg_id)))
        return True


def _runner_capturing_goal(captured: dict):
    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        captured["goal"] = goal
        captured["extra_context"] = extra_context
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok, prossigo com a credencial disponível."
        return t
    return _r


def _ep(runner, channel=None):
    ch = channel or FakeChannel()
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                         approval_mode="manual", spawn=lambda fn: fn())


def test_secret_stored_in_vault_encrypted_and_decryptable(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    captured: dict = {}
    ep = _ep(_runner_capturing_goal(captured))
    ep.handle("7", f"aqui está minha chave: {_TOKEN}")
    assert sv.vault_get("GITHUB_TOKEN") == _TOKEN
    raw = sv.vault_path().read_text(encoding="utf-8")
    assert _TOKEN not in raw                               # cifrado em repouso


def test_raw_value_absent_from_transcript_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    ep = _ep(_runner_capturing_goal({}))
    ep.handle("7", f"aqui está minha chave: {_TOKEN}")
    s = ep.session("7")
    hist_text = "\n".join(t for _, t in s.history)
    assert _TOKEN not in hist_text
    # varre TODO arquivo do home do agente (transcript) E do OKAMI_HOME (cofre) atrás do valor cru —
    # o cofre GRAVA algo derivado (o token Fernet), mas nunca o valor em si.
    import os
    leaked = []
    for base in (str(tmp_path), str(ep.home)):
        for root, _dirs, files in os.walk(base):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    with open(p, "rb") as f:
                        if _TOKEN.encode() in f.read():
                            leaked.append(p)
                except OSError:
                    continue
    assert leaked == [], f"valor cru vazou em: {leaked}"


def test_model_never_sees_raw_value_only_sanitized_note(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    captured: dict = {}
    ep = _ep(_runner_capturing_goal(captured))
    ep.handle("7", f"aqui está minha chave: {_TOKEN}, agora cria o repo")
    assert _TOKEN not in captured["goal"]
    assert _TOKEN not in captured["extra_context"]
    assert "GITHUB_TOKEN" in captured["goal"]               # nota saneada nomeia a credencial
    assert "cria o repo" in captured["goal"]                # resto da instrução preservado


def test_delete_message_called_on_original(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    ch = FakeChannel()
    ep = _ep(_runner_capturing_goal({}), channel=ch)
    ep._last_msg_id["7"] = "999"                            # simula o msg_id que o poll_once teria gravado
    ep.handle("7", f"aqui está minha chave: {_TOKEN}")
    assert ("7", "999") in ch.deleted


def test_confirmation_reply_sent_names_credential_never_value(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    ch = FakeChannel()
    ep = _ep(_runner_capturing_goal({}), channel=ch)
    ep.handle("7", f"aqui está minha chave: {_TOKEN}")
    body = "\n".join(t for _, t in ch.sent)
    assert _TOKEN not in body
    assert "GITHUB_TOKEN" in body
    assert "🔐" in body


def test_backward_compat_dotenv_secret_still_resolves(monkeypatch, tmp_path):
    """Segredo já existente no .env (fluxo antigo) continua resolvendo — o cofre NÃO substitui,
    só complementa (resolve_secret cai pro os.environ quando o nome não está no cofre)."""
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.setenv("LEGACY_FROM_DOTENV", "still-works")
    assert sv.resolve_secret("LEGACY_FROM_DOTENV") == "still-works"


def test_normal_message_no_false_positive_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    ch = FakeChannel()
    captured: dict = {}
    ep = _ep(_runner_capturing_goal(captured), channel=ch)
    ep.handle("7", "minha senha é hunter2, mas isso não é uma API key")
    assert captured["goal"] == "minha senha é hunter2, mas isso não é uma API key"
    assert ch.deleted == []                                 # nada apagado — não era segredo
    assert not any("🔐" in t for _, t in ch.sent)            # nenhuma confirmação de cofre disparada
    assert sv.vault_names() == []


def test_reply_ordering_fix_redacts_before_persisting():
    """Fix de ordem (~1499 vs ~1536 antigos): a resposta persistida no transcript é a MESMA redigida
    que sai pelo canal — não a crua."""
    secret = "sk-ABCDEF0123456789abcdef0123456789"  # pragma: allowlist secret

    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, f"a chave é {secret} pronto"
        return t

    ep = _ep(_r)
    ep.handle("7", "qual a chave?")
    s = ep.session("7")
    hist_text = "\n".join(t for _, t in s.history)
    assert secret not in hist_text                          # persistido JÁ redigido
    body = "\n".join(t for _, t in ep.channel.sent)
    assert secret not in body
