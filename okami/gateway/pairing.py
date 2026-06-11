"""Pareamento dinâmico (estilo Hermes pairing.py): chat não-autorizado pede acesso e recebe um CÓDIGO;
o DONO aprova pelo CLI (`okami pair approve <code>`) e o chat entra num allowlist PERSISTENTE — sem
editar agent.yaml na mão nem reiniciar o gateway. Deny-by-default continua: nada entra sem o dono.

Arquivo: `<home>/.okami/pairing.json` (0600 — guarda ids de usuário). Compartilhado entre o gateway
(que lê `is_approved`) e o CLI (que aprova) por serem o MESMO diretório do agente."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O/1/I (ambíguos) — fácil de ditar
_CODE_LEN = 6
_TTL = 3600.0                                     # pendência expira em 1h (não vira lixo eterno)


def _gen_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


class PairingStore:
    def __init__(self, home):
        self.path = Path(home) / ".okami" / "pairing.json"

    # --- persistência -----------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"approved": {}, "pending": {}}
        data.setdefault("approved", {})
        data.setdefault("pending", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)                       # ids de usuário → privado
        except OSError:
            pass
        tmp.replace(self.path)                     # troca atômica

    # --- pedido/pendência -------------------------------------------------
    def request_code(self, chat_id, *, now: float | None = None, ttl: float = _TTL) -> str:
        """Devolve o código de pareamento deste chat (gera se não houver pendência viva). '' se já
        aprovado. Dedup por chat: mesma pendência → MESMO código (não spamma códigos novos)."""
        now = time.time() if now is None else now
        cid = str(chat_id)
        data = self._load()
        if cid in data["approved"]:
            return ""
        for code, p in data["pending"].items():    # já tem pendência viva → reusa o código
            if p.get("chat_id") == cid and now - p.get("ts", 0) < ttl:
                return code
        code = _gen_code()
        while code in data["pending"]:              # colisão (raríssima) → outro
            code = _gen_code()
        data["pending"][code] = {"chat_id": cid, "ts": now}
        self._save(data)
        return code

    def pending(self, *, now: float | None = None, ttl: float = _TTL) -> list[dict]:
        now = time.time() if now is None else now
        data = self._load()
        return [{"code": c, "chat_id": p["chat_id"], "ts": p["ts"]}
                for c, p in data["pending"].items() if now - p.get("ts", 0) < ttl]

    # --- aprovação --------------------------------------------------------
    def approve(self, code: str, *, now: float | None = None, ttl: float = _TTL) -> str | None:
        """Aprova um código pendente (move p/ approved). Devolve o chat_id, ou None se inválido/expirado."""
        now = time.time() if now is None else now
        data = self._load()
        p = data["pending"].get((code or "").strip().upper())
        if not p or now - p.get("ts", 0) >= ttl:
            return None
        cid = p["chat_id"]
        data["approved"][cid] = now
        del data["pending"][(code or "").strip().upper()]
        self._save(data)
        return cid

    def approve_chat(self, chat_id, *, now: float | None = None) -> None:
        """Aprova um chat_id diretamente (o dono já conhece o id) — sem precisar de código."""
        now = time.time() if now is None else now
        data = self._load()
        data["approved"][str(chat_id)] = now
        data["pending"] = {c: p for c, p in data["pending"].items() if p.get("chat_id") != str(chat_id)}
        self._save(data)

    def revoke(self, chat_id) -> bool:
        data = self._load()
        if str(chat_id) in data["approved"]:
            del data["approved"][str(chat_id)]
            self._save(data)
            return True
        return False

    # --- consulta ---------------------------------------------------------
    def approved(self) -> list[str]:
        return list(self._load()["approved"].keys())

    def is_approved(self, chat_id) -> bool:
        return str(chat_id) in self._load()["approved"]
