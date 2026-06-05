"""Aprovação como OBJETO persistente e single-use (#7) — estilo Hermes/OpenClaw.

Antes, a aprovação era um nonce volátil em memória (`_pending[chat]`): sumia no restart e não
registrava NADA. Agora cada pedido de go/no-go vira um registro durável em `.okami/approvals.jsonl`:

    {approval_id, tool, args_hash, risk, category, surface, chat_id, user_id,
     created_at, expires_at, used_at, decision}

Garantias:
- **single-use**: `consume()` marca `used_at` — clicar/usar de novo (mesmo após restart) é recusado;
- **expiração material**: `expires_at` no objeto; consumir depois do prazo é recusado;
- **binding aos args**: `args_hash` no registro casa com o hash da ação EXATA (core.approval.args_hash);
- **auditável**: log append-only, sob o mesmo _FileLock do núcleo (sem corrida multi-processo).
O harness continua bloqueando na fila p/ a resposta; o store é a fonte de verdade do "ainda vale?".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from okami.core.filelock import _FileLock


@dataclass
class Approval:
    approval_id: str
    tool: str
    args_hash: str
    risk: str
    category: str
    surface: str
    chat_id: str
    user_id: str
    created_at: float
    expires_at: float
    used_at: float | None = None
    decision: str = ""            # "" (pendente) | approved | denied | expired

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConsumeResult:
    ok: bool
    reason: str
    approval: Approval | None = None


class ApprovalStore:
    def __init__(self, workspace, clock=None):
        import time
        self.ws = Path(workspace)
        self.path = self.ws / ".okami" / "approvals.jsonl"
        self._clock = clock or time.time

    # ----------------------------------------------------------------- io (append-only)
    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)   # o .lock precisa do dir existir ANTES do lock

    def _append(self, rec: dict) -> None:
        self._ensure_dir()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for ln in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return out

    def _latest(self, approval_id: str) -> dict | None:
        """Último registro (estado atual) p/ um id — o log é append-only, a última linha vence."""
        found = None
        for r in self._records():
            if r.get("approval_id") == approval_id:
                found = r
        return found

    # ----------------------------------------------------------------- ciclo de vida
    def create(self, *, approval_id: str, tool: str, args_hash: str, risk: str, category: str,
               surface: str, chat_id: str, user_id: str = "", ttl: float = 300.0) -> Approval:
        now = self._clock()
        appr = Approval(approval_id=approval_id, tool=tool, args_hash=args_hash, risk=risk,
                        category=category, surface=surface, chat_id=str(chat_id),
                        user_id=str(user_id or chat_id), created_at=round(now, 3),
                        expires_at=round(now + max(1.0, ttl), 3))
        self._ensure_dir()
        with _FileLock(self.path):
            self._append(appr.to_dict())
        return appr

    def consume(self, approval_id: str, decision: str, *, args_hash: str | None = None) -> ConsumeResult:
        """Valida (existe? não expirou? não usado? args batem?) e marca used_at. ATÔMICO sob lock."""
        self._ensure_dir()
        with _FileLock(self.path):
            rec = self._latest(approval_id)
            if rec is None:
                return ConsumeResult(False, "desconhecido")
            appr = Approval(**rec)
            if appr.used_at is not None:
                return ConsumeResult(False, "já usado", appr)        # single-use (sobrevive a restart)
            now = self._clock()
            if now > appr.expires_at:
                self._append({**rec, "decision": "expired", "used_at": round(now, 3)})
                return ConsumeResult(False, "expirado", appr)
            if args_hash is not None and appr.args_hash and args_hash != appr.args_hash:
                return ConsumeResult(False, "args divergem", appr)   # aprovação não vale p/ outra ação
            appr.used_at = round(now, 3)
            appr.decision = decision
            self._append(appr.to_dict())
            return ConsumeResult(True, "ok", appr)

    def expire_if_pending(self, approval_id: str) -> None:
        """Marca como expirado um pedido que ficou sem resposta (timeout do go/no-go)."""
        self._ensure_dir()
        with _FileLock(self.path):
            rec = self._latest(approval_id)
            if rec and rec.get("used_at") is None:
                self._append({**rec, "decision": "expired", "used_at": round(self._clock(), 3)})

    def get(self, approval_id: str) -> Approval | None:
        rec = self._latest(approval_id)
        return Approval(**rec) if rec else None

    def pending(self) -> list[Approval]:
        now = self._clock()
        return [Approval(**r) for r in self._records()
                if r.get("used_at") is None and r.get("expires_at", 0) > now
                and self._latest(r["approval_id"]).get("used_at") is None]
