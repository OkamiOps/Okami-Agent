"""Checkpoints de arquivo (estilo Hermes) — snapshot ANTES de cada escrita → rollback.

Rede de segurança complementar ao go/no-go (§12): toda escrita de `write_file` registra o estado
ANTERIOR do arquivo num journal append-only (`<ws>/.okami/checkpoints/journal.jsonl`). `rollback(n)`
desfaz as últimas n escritas (restaura o conteúdo de antes, ou apaga o arquivo se ele não existia).

Defesas do journal (#3/#10):
- **lock** (core.filelock) em todo append e rollback → sem corrida entre processos/turnos;
- **tamper-evidence**: cada entrada leva um HMAC ENCADEADO (mac = HMAC(key, prev_mac+payload)) com
  chave por-workspace 0600. Adulterar/inserir/reordenar uma linha quebra a cadeia → o rollback
  PULA a entrada (não restaura conteúdo forjado apontando p/ /etc/passwd);
- **jail + sem segredo + cap por snapshot** (já de #5);
- **cap TOTAL do journal** + compactação segura (re-encadeia ao podar o mais antigo).
Best-effort: se o snapshot falhar, a escrita segue normal (nunca quebra o agente).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from okami.core.filelock import _FileLock


class Checkpoints:
    def __init__(self, workspace):
        self.ws = Path(workspace)
        self.dir = self.ws / ".okami" / "checkpoints"
        self.journal = self.dir / "journal.jsonl"
        self.keyfile = self.dir / ".hmac.key"
        self._key: bytes | None = None

    _MAX_SNAP = 2_000_000          # não captura arquivo gigante no journal (cap por entrada)
    _MAX_JOURNAL = 5_000_000       # cap TOTAL: acima disso, poda o mais antigo e re-encadeia

    # ----------------------------------------------------------------- chave + HMAC encadeado
    def _load_key(self) -> bytes:
        if self._key is not None:
            return self._key
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.keyfile.exists():
            self._key = self.keyfile.read_bytes()
        else:
            self._key = secrets.token_bytes(32)
            self.keyfile.write_bytes(self._key)
            try:
                os.chmod(self.keyfile, 0o600)           # chave de integridade não fica legível p/ todos
            except OSError:
                pass
        return self._key

    @staticmethod
    def _payload(entry: dict) -> dict:
        """Só os campos cobertos pelo MAC (sem o próprio mac), em ordem estável."""
        return {"path": entry.get("path"), "before": entry.get("before"),
                "existed": entry.get("existed"), "ts": entry.get("ts")}

    def _mac(self, prev: str, payload: dict) -> str:
        msg = (prev + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode("utf-8")
        return hmac.new(self._load_key(), msg, hashlib.sha256).hexdigest()

    def _verify(self, ents: list[dict]) -> list[bool]:
        """True/False por entrada: a cadeia HMAC bate até aqui? Uma quebra contamina o resto."""
        oks, prev, broken = [], "", False
        for e in ents:
            if broken:
                oks.append(False)
                continue
            expect = self._mac(prev, self._payload(e))
            ok = hmac.compare_digest(expect, str(e.get("mac", "")))
            oks.append(ok)
            if not ok:
                broken = True                           # do ponto adulterado em diante, nada é confiável
            else:
                prev = expect
        return oks

    # ----------------------------------------------------------------- jail (#5)
    def _safe(self, rel: str):
        """Resolve `rel` DENTRO do workspace: rel absoluto/escape → None. Recusa caminho sensível."""
        from okami.core.file_safety import safe_path
        from okami.core.tools import _SENSITIVE_PATH
        try:
            p = safe_path(self.ws, rel)
        except ValueError:
            return None
        if _SENSITIVE_PATH.search(rel) or _SENSITIVE_PATH.search(str(p)):
            return None
        return p

    # ----------------------------------------------------------------- append / read
    def snapshot(self, rel: str) -> None:
        """Grava o estado ATUAL de `rel` (antes de uma escrita) — jailed + sem segredo + cap + HMAC."""
        p = self._safe(rel)
        if p is None:
            return
        before = None
        if p.exists():
            try:
                if p.stat().st_size > self._MAX_SNAP:
                    return
                before = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return
        self.dir.mkdir(parents=True, exist_ok=True)
        with _FileLock(self.journal):                   # serializa append (multi-processo/turno)
            prev = self._tail_mac()
            payload = {"path": rel, "before": before, "existed": before is not None,
                       "ts": round(time.time(), 3)}
            entry = {**payload, "mac": self._mac(prev, payload)}
            with self.journal.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._maybe_compact()

    def _tail_mac(self) -> str:
        ents = self.entries()
        return str(ents[-1].get("mac", "")) if ents else ""

    def entries(self) -> list[dict]:
        if not self.journal.exists():
            return []
        out = []
        for ln in self.journal.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return out

    def _rewrite(self, ents: list[dict]) -> None:
        """Re-encadeia (macs frescos do zero) e grava o journal de forma atômica (sob lock do caller)."""
        lines, prev = [], ""
        for e in ents:
            payload = self._payload(e)
            mac = self._mac(prev, payload)
            prev = mac
            lines.append(json.dumps({**payload, "mac": mac}, ensure_ascii=False))
        tmp = self.journal.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8", newline="\n")
        os.replace(tmp, self.journal)                   # rename atômico

    def _maybe_compact(self) -> None:
        """Cap TOTAL: se o journal passou do limite, poda as entradas MAIS ANTIGAS e re-encadeia."""
        try:
            if self.journal.stat().st_size <= self._MAX_JOURNAL:
                return
        except OSError:
            return
        ents = self.entries()
        while len(ents) > 1 and sum(len(json.dumps(e, ensure_ascii=False)) for e in ents) > self._MAX_JOURNAL:
            ents.pop(0)                                 # descarta o snapshot mais velho primeiro
        self._rewrite(ents)

    # ----------------------------------------------------------------- rollback
    def rollback(self, n: int = 1) -> list[str]:
        """Reverte as últimas n escritas (sob lock); pula entradas adulteradas (cadeia HMAC quebrada)."""
        with _FileLock(self.journal):
            ents = self.entries()
            if not ents or n <= 0:
                return []
            oks = self._verify(ents)
            undone, undone_ok = ents[-n:], oks[-n:]
            reverted = []
            for e, ok in zip(reversed(undone), reversed(undone_ok)):
                if not ok:
                    continue                            # entrada adulterada (HMAC não bate) → ignora
                p = self._safe(e.get("path", ""))
                if p is None:
                    continue                            # aponta p/ fora do ws / sensível → ignora
                if e.get("existed"):
                    from okami.core.file_safety import write_text_atomic
                    write_text_atomic(p, e.get("before") or "")
                elif p.exists():
                    p.unlink()
                reverted.append(e["path"])
            keep = ents[: len(ents) - len(undone)]
            self._rewrite(keep) if keep else (self.journal.unlink() if self.journal.exists() else None)
            return reverted
