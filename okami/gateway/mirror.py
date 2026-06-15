"""Espelho de entrega cross-sessão — PURO (não toca store, store/IO ficam no caller).

Problema (paridade Hermes): quando o agente entrega algo numa sessão por um caminho que
NÃO é a fala do usuário — cron, notify, send_message — esse texto não aparece no transcript
da sessão-alvo. No próximo turno o agente do outro lado não sabe que ELE mesmo já mandou aquilo
e acaba repetindo (ou pior, se contradizendo). A solução é "espelhar": gravar a entrega como
uma fala do AGENTE, marcada com a origem, p/ ele se reconhecer.

Este módulo só decide O QUÊ gravar (papel + texto formatado). QUEM grava é o gateway, via
`_append_turn(chat_id, s, papel, texto)`. Mantido puro p/ ser trivialmente testável e fail-safe.
"""

from __future__ import annotations

from okami.core.redact import redact

# Papel no transcript: a entrega é uma fala do PRÓPRIO agente (não do usuário) — assim ele a lê
# como "isto fui eu que mandei" e não como instrução nova. Casa com a convenção USER/AGENTE
# usada em gateway/sessions.py e endpoint._append_turn.
_ROLE = "AGENTE"

# Origens que SÃO entrega proativa do agente → espelham. "user" (a fala do dono) NÃO entra:
# ela já chega ao transcript pelo fluxo normal; espelhá-la duplicaria a mensagem.
_MIRRORED_SOURCES = frozenset({"cron", "notify", "send_message"})


def should_mirror(source: str) -> bool:
    """True se `source` é uma ENTREGA do agente que merece virar espelho no transcript.

    Best-effort: tolera None/lixo/espaço/maiúscula e nunca levanta — origem desconhecida → False
    (não espelha por engano)."""
    if not source or not isinstance(source, str):
        return False
    return source.strip().lower() in _MIRRORED_SOURCES


def mirror_record(text: str, *, source: str = "cron") -> tuple[str, str]:
    """Devolve (papel, texto_formatado) p/ gravar a entrega no transcript da sessão-alvo.

    Ex.: mirror_record("oi", source="cron") -> ("AGENTE", "[enviado via cron] oi").
    O prefixo carrega a origem p/ o agente saber que a fala foi entrega automática (não repete
    nem contradiz). Texto passa por `redact` — segredo não entra cru no histórico durável.
    Fail-safe: entrada não-str/None não derruba o caller (vira string vazia formatada)."""
    raw = text if isinstance(text, str) else ("" if text is None else str(text))
    src = source.strip() if isinstance(source, str) and source.strip() else "cron"
    formatted = redact(f"[enviado via {src}] {raw}")
    return _ROLE, formatted
