"""Sessões em 2 CAMADAS (estilo OpenClaw, §13) — metadados + transcript append-only.

Por que 2 camadas (e não 1 JSON por chat):
- **Store** (`sessions.json`): mapa pequeno e mutável `chat_id -> entry` (sessionId, contadores,
  timestamps, yolo/overlay/resume_attempts). Reescrito ATOMICAMENTE (temp+replace) — é minúsculo.
- **Transcript** (`<chat>.jsonl`): APPEND-ONLY, uma linha por turno, em árvore (`id`/`parentId`).
  Nunca reescreve a conversa inteira → crash-safe (uma queda no meio perde no máx. a última linha)
  e escalável (conversa gigante não vira um write gigante). Suporta nós de SUMMARY (compaction §6.4).

O gateway (§13) usa isto: rebuild do histórico = ler a cauda do transcript; gravar um turno = append.
"""

from __future__ import annotations

import atexit
import json
import os
import time
from pathlib import Path

_HELD: set[str] = set()        # locks deste processo (p/ limpar na saída)


def _proc_start(pid: int) -> str:
    """Start-time do processo (Linux /proc, campo 22) p/ detectar PID RECICLADO. '' onde não dá (macOS/Win)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            raw = f.read()
        return raw[raw.rfind(")") + 1:].split()[19]      # após o comm: starttime é o 20º token (campo 22)
    except Exception:  # noqa: BLE001
        return ""


def _cleanup_held_locks() -> None:
    """Solta os locks DESTE processo na saída (atexit). Crash/SIGTERM é coberto pelo stale-reclaim."""
    for lk in list(_HELD):
        try:
            if int(json.loads(Path(lk).read_text(encoding="utf-8")).get("pid", -1)) == os.getpid():
                Path(lk).unlink()
        except Exception:  # noqa: BLE001
            pass


atexit.register(_cleanup_held_locks)


class _FileLock:
    """Lock cross-platform por arquivo (.lock atômico O_EXCL) — concorrência multi-processo (P0.5).

    O lock guarda o DONO (pid + criação). Rouba o lock só se o dono MORREU (os.kill(pid,0)) ou se está
    velho demais. Ao soltar, só remove o lock que EU criei (não atropela o de outro). Se não conseguir
    em `timeout`s, segue mesmo assim — mas AVISA no log (não é mais silencioso)."""

    def __init__(self, target: Path, timeout: float = 10.0, stale: float = 60.0):
        self.lock = Path(str(target) + ".lock")
        self.timeout, self.stale = timeout, stale
        self.acquired = False

    def _owner_alive(self) -> bool:
        try:
            info = json.loads(self.lock.read_text(encoding="utf-8"))
            pid = int(info.get("pid", 0))
        except Exception:  # noqa: BLE001 — lock recém-criado/meio-escrito (janela entre create e write):
            return True     # assume VIVO p/ NÃO roubar (evita corrida); `age > stale` ainda reclama o real-órfão
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)                               # processo vivo? (POSIX; ProcessLookupError se morto)
        except ProcessLookupError:
            return False
        except OSError:
            return True                                  # sem permissão p/ sinalizar → existe (conservador)
        stored, cur = info.get("start", ""), _proc_start(pid)   # anti PID-reuse: start-time diferente = outro proc
        return not (stored and cur and stored != cur)

    def _age(self) -> float:
        try:
            return time.time() - self.lock.stat().st_mtime
        except OSError:
            return 0.0

    def __enter__(self):
        start = time.time()
        while True:
            try:
                fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "start": _proc_start(os.getpid()),
                                         "created": time.time()}).encode("utf-8"))
                os.close(fd)
                self.acquired = True
                _HELD.add(str(self.lock))                # registra p/ limpeza na saída (atexit)
                return self
            except FileExistsError:
                if not self._owner_alive() or self._age() > self.stale:   # dono morto OU velho → rouba
                    try:
                        self.lock.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() - start > self.timeout:
                    from okami.log import warn
                    warn(f"session lock ocupado >{self.timeout:.0f}s ({self.lock.name}) — seguindo sem lock")
                    return self                          # best-effort, mas agora REGISTRA
                time.sleep(0.03)

    def __exit__(self, *exc):
        if self.acquired:                                # só removo o lock que EU criei
            _HELD.discard(str(self.lock))
            try:
                self.lock.unlink()
            except OSError:
                pass


class TranscriptStore:
    def __init__(self, root, *, subdir: str = "sessions", clock=time.time):
        self.dir = Path(root) / ".okami" / subdir   # subdir: "sessions" (DM) | "groups" (§10)
        self._clock = clock                      # injetável p/ teste determinístico

    # ----------------------------------------------------------------- store (metadados)
    def _store_path(self) -> Path:
        return self.dir / "sessions.json"

    def _tx_path(self, chat_id) -> Path:
        return self.dir / f"{chat_id}.jsonl"

    def load_store(self) -> dict:
        p = self._store_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_store(self, store: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._store_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8", newline="\n")
        os.replace(tmp, self._store_path())      # rename atômico

    def entry(self, chat_id) -> dict:
        return self.load_store().get(str(chat_id), {})

    def update_entry(self, chat_id, **fields) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        with _FileLock(self._store_path()):          # read-modify-write atômico entre processos
            store = self.load_store()
            e = store.setdefault(str(chat_id), {})
            e.update(fields)
            e["updated_at"] = self._clock()
            self._save_store(store)
        return e

    def add_usage(self, chat_id, usage: dict, *, served_by: str = "") -> dict:
        """Acumula os tokens do turno nos metadados da sessão (sob lock cross-process). `usage` é o
        dict de `CanonicalUsage.to_dict()`. Custo é DERIVADO na hora de mostrar (preço muda retroativo)."""
        if not usage:
            return self.entry(chat_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        with _FileLock(self._store_path()):
            store = self.load_store()
            e = store.setdefault(str(chat_id), {})
            acc = e.setdefault("usage", {})
            for k, v in usage.items():
                acc[k] = int(acc.get(k, 0)) + int(v or 0)
            if served_by:
                e["served_by"] = served_by
            e["updated_at"] = self._clock()
            self._save_store(store)
        return e

    def ids(self) -> list[str]:
        return list(self.load_store().keys())

    # ----------------------------------------------------------------- transcript (append-only)
    def append(self, chat_id, role: str, text: str) -> str:
        """Acrescenta UM nó ao transcript e atualiza os metadados — TUDO sob UM lock por chat (P0.5).

        Antes: lia node_count, escrevia e atualizava em passos separados → duas escritas concorrentes
        pegavam o mesmo node_count (id duplicado / metadado perdido). Agora o lock por chat serializa
        a transação inteira (count fresco → append → update_entry)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = self._clock()
        with _FileLock(self._tx_path(chat_id)):          # serializa a transação do MESMO chat
            n = int(self.entry(chat_id).get("node_count", 0))   # node_count FRESCO sob o lock
            node = {"id": f"{chat_id}-{n}", "parentId": (f"{chat_id}-{n - 1}" if n else None),
                    "role": role, "text": text, "ts": ts}
            with self._tx_path(chat_id).open("a", encoding="utf-8") as f:
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
            self.update_entry(chat_id, node_count=n + 1, last_node_id=node["id"], last_role=role,
                              last_interaction_at=ts)     # store lock (alvo diferente → sem deadlock)
        return node["id"]

    def read(self, chat_id, limit: int | None = None) -> list[dict]:
        p = self._tx_path(chat_id)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if limit is not None:
            lines = lines[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:        # linha truncada por um crash no meio do append → ignora
                pass
        return out

    def history(self, chat_id, limit: int = 16) -> list[tuple[str, str]]:
        """Histórico recente como (papel, texto). Papel = USER/AGENTE (DM) ou o id do agente (grupo §10).
        A partir do último nó SUMMARY (compaction §6.4): o resumo SUBSTITUI o prefixo antigo."""
        nodes = self.read(chat_id)
        last_sum = max((i for i, n in enumerate(nodes) if n.get("role") == "SUMMARY"), default=-1)
        if last_sum >= 0:
            nodes = nodes[last_sum:]                  # resumo + o que veio depois
        return [(n.get("role", ""), n.get("text", "")) for n in nodes[-limit:] if n.get("role")]

    def compact(self, chat_id, summary: str) -> str:
        """Compaction §6.4: append de um nó SUMMARY (resume o que veio antes — nada se perde, o
        transcript completo continua no disco; só o REBUILD passa a usar o resumo)."""
        return self.append(chat_id, "SUMMARY", summary)

    def reset(self, chat_id) -> None:
        """/new — ARQUIVA o transcript (não apaga) e zera a contagem; preserva yolo/overlay."""
        p = self._tx_path(chat_id)
        if p.exists():
            try:
                p.rename(self.dir / f"{chat_id}.{int(self._clock())}.reset.jsonl")
            except OSError:
                pass
        self.update_entry(chat_id, node_count=0, last_node_id=None, last_role=None)

    # ----------------------------------------------------------------- session service (/sessions /resume /export)
    def archives(self, chat_id) -> list[dict]:
        """Sessões ARQUIVADAS (por /new) deste chat: [{ts, name, turns}], mais nova primeiro."""
        out = []
        for p in self.dir.glob(f"{chat_id}.*.reset.jsonl"):
            try:
                ts = int(p.name.split(".")[-3])
            except (ValueError, IndexError):
                ts = 0
            turns = len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) // 2
            out.append({"ts": ts, "name": p.name, "turns": turns})
        return sorted(out, key=lambda a: a["ts"], reverse=True)

    def resume(self, chat_id, name: str) -> list[tuple[str, str]]:
        """Retoma uma sessão arquivada: arquiva a atual e torna `name` o transcript ativo. Devolve o histórico."""
        arch = self.dir / name
        if not name.startswith(f"{chat_id}.") or not arch.exists():
            raise FileNotFoundError(name)
        self.reset(chat_id)                          # arquiva a sessão atual antes de trocar
        arch.rename(self._tx_path(chat_id))          # a arquivada vira a ativa
        nodes = self.read(chat_id)
        self.update_entry(chat_id, node_count=len(nodes),
                          last_node_id=(nodes[-1].get("id") if nodes else None),
                          last_role=(nodes[-1].get("role") if nodes else None))
        return [(n.get("role", ""), n.get("text", "")) for n in nodes if n.get("role")]

    def export(self, chat_id, path) -> Path:
        """Exporta o transcript como Markdown legível. Devolve o caminho escrito."""
        nodes = self.read(chat_id)
        lines = [f"# Conversa {chat_id}\n"]
        for n in nodes:
            who = {"USER": "você", "AGENTE": "okami", "SUMMARY": "— resumo —"}.get(n.get("role", ""),
                                                                                   n.get("role", ""))
            lines.append(f"**{who}:** {n.get('text', '')}\n")
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return out

    # ----------------------------------------------------------------- maintenance (poda)
    def prune(self, max_sessions: int = 500, max_age_days: float = 30.0) -> int:
        """Estilo OpenClaw session.maintenance: remove sessões velhas/excedentes (store + transcript)."""
        store = self.load_store()
        if not store:
            return 0
        items = sorted(store.items(), key=lambda kv: kv[1].get("updated_at", 0), reverse=True)
        cutoff = self._clock() - max_age_days * 86400
        keep, removed = {}, 0
        for i, (cid, e) in enumerate(items):
            if i >= max_sessions or e.get("updated_at", 0) < cutoff:
                try:
                    self._tx_path(cid).unlink()
                except OSError:
                    pass
                removed += 1
            else:
                keep[cid] = e
        if removed:
            self._save_store(keep)
        return removed
