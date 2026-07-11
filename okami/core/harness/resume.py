"""Checkpoint estruturado de turno + seed no resume (gap Hermes replay_cleanup + crash-resume).

PROBLEMA: um crash no MEIO do loop de tools (kill/OOM/restart da VPS) perde `self.messages` (RAM). No
resume, o harness reconstruía `[system, user]` do zero — o modelo não lembrava dos passos JÁ feitos e
podia refazer ou divergir. Aqui persistimos as mensagens ESTRUTURADAS (com tool_calls/role=tool) a cada
passo; no resume, carregamos e consertamos o tail órfão (tool_call sem resultado quando o processo morreu
no meio da chamada) antes de re-alimentar o loop. Best-effort total: qualquer erro → comportamento antigo.
"""
from __future__ import annotations

import json
from pathlib import Path

from okami.core.harness.native_history import repair_native_history

_CKPT_NAME = "turn_ckpt.json"


def _ckpt_path(workspace) -> Path:
    return Path(workspace) / ".okami" / _CKPT_NAME


def write_checkpoint(workspace, messages: list[dict], ts: float) -> None:
    """Grava as mensagens estruturadas do turno (atômico, best-effort). NUNCA levanta — checkpoint é
    seguro-de-perder; falhar aqui não pode derrubar o turno."""
    try:
        p = _ckpt_path(workspace)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"ts": ts, "messages": messages}, ensure_ascii=False)
        from okami.core.safe_io import write_atomic
        write_atomic(p, payload)
    except Exception:  # noqa: BLE001 — checkpoint é best-effort
        pass


def load_checkpoint(workspace, *, max_age_s: float, now: float) -> list[dict] | None:
    """Carrega o checkpoint SE fresco (dentro de max_age_s) e válido. Repara o tail órfão (tool_call sem
    resultado — o processo morreu no meio) antes de devolver. Fora da janela/ inválido/ ausente → None
    (cai no comportamento antigo: reconstrói do zero). NÃO consome o arquivo (clear_checkpoint faz isso)."""
    try:
        p = _ckpt_path(workspace)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0) or 0)
        if not ts or (now - ts) > max_age_s:            # velho → não ressuscita turno morto (paridade resume_freshness)
            return None
        msgs = data.get("messages")
        if not isinstance(msgs, list) or len(msgs) < 2:
            return None
        repaired = repair_native_history(msgs, interrupted=True)
        return repaired if repaired and len(repaired) >= 2 else None
    except Exception:  # noqa: BLE001 — qualquer problema → comportamento antigo
        return None


def clear_checkpoint(workspace) -> None:
    """Apaga o checkpoint (turno concluído/abandonado — não deve ser re-seedado). Best-effort."""
    try:
        _ckpt_path(workspace).unlink()
    except Exception:  # noqa: BLE001
        pass
