"""Scheduling (§11) — cron + intervalos + one-shot, estilo OpenClaw/Hermes.

Persiste jobs em `<root>/.okami/cron.json`, decide o que está VENCIDO e executa pela MESMA máquina
de estados do harness (§3) — tarefa agendada também nunca trava. Formatos de schedule:
- **intervalo**: "30m", "1h", "2h30m", "90s", "every 1h".
- **cron** (5 campos: min hora dia mês diadassemana): "0 9 * * 1" (seg 9h), "*/15 * * * *".
- **one-shot**: ISO "2026-06-10T09:00" (roda uma vez).
O resultado é entregue de volta num chat (gateway) ou impresso (CLI). Clock injetável p/ teste.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

_INTERVAL_RE = re.compile(r"(\d+)\s*([smhd])")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _slug(text: str) -> str:
    """Id CURTO de cron job a partir do prompt — tópico, não a frase literal do usuário (core.naming)."""
    from okami.core.naming import short_name
    return short_name(text, fallback="job")


def _parse_interval(spec: str) -> int | None:
    s = re.sub(r"\s+", "", spec.lower().replace("every", ""))
    if not s or not re.fullmatch(r"(\d+[smhd])+", s):     # aceita múltiplas unidades: "2h30m"
        return None
    return sum(int(n) * _UNIT[u] for n, u in _INTERVAL_RE.findall(s)) or None


def _parse_iso(spec: str) -> float | None:
    try:
        return datetime.fromisoformat(spec.replace("at ", "").strip()).timestamp()
    except (ValueError, TypeError):
        return None


# Preâmbulo de CONTEXTO HEADLESS — toda tarefa agendada roda SEM ninguém presente. Sem isto, num ponto
# ambíguo o agente usaria need_input/clarify e travaria (não há quem responda). Aplicado no gateway E na
# CLI p/ comportamento idêntico (paridade Hermes: bloco 'no user present' do cron).
CRON_HEADLESS_PREAMBLE = (
    "[TAREFA AGENDADA — rodando sozinha, SEM ninguém presente para responder agora. NÃO pergunte nem "
    "peça confirmação (need_input/clarify travam aqui, ninguém responde): decida com o default mais "
    "razoável e ENTREGUE tudo direto na resposta final.]\n\n")


def headless_prompt(prompt: str) -> str:
    """Prefixa o preâmbulo headless ao prompt de um job agendado (não-duplica se já tiver)."""
    p = prompt or ""
    return p if p.startswith("[TAREFA AGENDADA") else CRON_HEADLESS_PREAMBLE + p


def parse_schedule(spec: str) -> dict:
    """Classifica o schedule: {'kind': 'cron'|'interval'|'once', ...}."""
    spec = spec.strip()
    parts = spec.split()
    if len(parts) == 5 and all(re.fullmatch(r"[\d*/,\-]+", p) for p in parts):
        return {"kind": "cron", "expr": spec}
    secs = _parse_interval(spec)
    if secs:
        return {"kind": "interval", "seconds": secs}
    return {"kind": "once", "at": spec}


def _cron_field(field: str, value: int, lo: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        if part.startswith("*/"):
            step = int(part[2:])
            if step and (value - lo) % step == 0:
                return True
        elif "-" in part:
            a, b = part.split("-")
            if int(a) <= value <= int(b):
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def _cron_match(expr: str, dt: datetime) -> bool:
    mi, ho, dom, mo, dow = expr.split()
    cron_dow = (dt.weekday() + 1) % 7        # cron: 0=domingo; Python: 0=segunda
    return (_cron_field(mi, dt.minute, 0) and _cron_field(ho, dt.hour, 0)
            and _cron_field(dom, dt.day, 1) and _cron_field(mo, dt.month, 1)
            and _cron_field(dow, cron_dow, 0))


def is_due(schedule: str, now_ts: float, last_run: float | None) -> bool:
    s = parse_schedule(schedule)
    if s["kind"] == "interval":
        return last_run is None or (now_ts - last_run) >= s["seconds"]
    if s["kind"] == "cron":
        if not _cron_match(s["expr"], datetime.fromtimestamp(now_ts)):
            return False
        return last_run is None or int(last_run // 60) != int(now_ts // 60)   # 1x por minuto no máx.
    if s["kind"] == "once":
        target = _parse_iso(s["at"])
        return last_run is None and target is not None and now_ts >= target
    return False


def _time_phrase(low: str, now_ts: float) -> str | None:
    """Frase de tempo → schedule (ISO p/ one-shot relativo, cron p/ recorrente)."""
    m = re.search(r"daqui a (\d+)\s*(min|minuto|m|hora|h|dia|d)", low)
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        secs = n * {"m": 60, "h": 3600, "d": 86400}.get(u, 60)
        return datetime.fromtimestamp(now_ts + secs).isoformat(timespec="minutes")
    hora = re.search(r"\bas\s+(\d{1,2})\b", low) or re.search(r"\b(\d{1,2})\s*h\b", low)
    h = int(hora.group(1)) if hora else 9
    if "todo dia" in low or "todos os dias" in low or "diariamente" in low:
        return f"0 {h} * * *"                         # cron diário
    dias = {"segunda": 1, "terca": 2, "terça": 2, "quarta": 3, "quinta": 4, "sexta": 5,
            "sabado": 6, "sábado": 6, "domingo": 0}
    for nome, dow in dias.items():
        if f"toda {nome}" in low or f"todo {nome}" in low or f"todas as {nome}" in low:
            return f"0 {h} * * {dow}"                  # cron semanal
    if "amanha" in low or "amanhã" in low:
        return datetime.fromtimestamp(now_ts + 86400).replace(hour=h, minute=0,
                                                              second=0, microsecond=0).isoformat(timespec="minutes")
    return None


def infer_commitment(text: str, now_ts: float) -> tuple[str, str] | None:
    """Detecta um COMPROMISSO na fala ("me lembra de X amanhã", "todo dia às 9 faça Y") →
    (schedule, prompt) p/ virar um job. Estilo OpenClaw 'inferred commitments'. None se não houver."""
    import unicodedata
    low = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    if not re.search(r"\blembr|\blembrete|\bagend", low):     # gatilho explícito (evita falso-positivo)
        return None
    sched = _time_phrase(low, now_ts)
    if not sched:
        return None
    m = re.search(r"lembr\w*\s+(?:de\s+|que\s+|para\s+|pra\s+)?(.*)", text, re.IGNORECASE)
    action = (m.group(1) if m else text).strip().rstrip("?.! ")
    action = re.sub(r"\b(amanh[ãa]|hoje|daqui a \d+\s*\w+|todo dia|todos os dias|toda[s]?\s+\w+|"
                    r"[àa]s?\s*\d{1,2}\s*h?)\b", "", action, flags=re.IGNORECASE)
    action = re.sub(r"\s{2,}", " ", action).strip(" ,") or text.strip()
    return sched, action[:120]


def gate_allows(job: dict, cwd: str = ".", timeout: float = 30.0) -> bool:
    """Wake-gate (estilo Hermes): job com `gate` (comando shell BARATO) roda o gate ANTES do agente —
    exit 0 = acorda o LLM; exit ≠0 = pula em silêncio ('nada mudou, não gasta token'). Sem gate ou
    gate com ERRO de execução → fail-open (True): um gate quebrado não pode calar o job pra sempre."""
    cmd = str(job.get("gate") or "").strip()
    if not cmd:
        return True
    import subprocess
    from okami.core.tools import sanitized_env
    try:
        # gate é comando do OPERADOR (config confiável), não input do modelo → shell=True ok.
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,  # nosec B602
                           timeout=timeout, env=sanitized_env())  # nosemgrep — gate do operador (B602 acima)
        return r.returncode == 0
    except Exception:  # noqa: BLE001 — erro de spawn/timeout → fail-open
        return True


def next_run_at(schedule: str, *, now: float, last_run: float | None) -> float | None:
    """Quando o job roda DE NOVO (epoch), p/ previsibilidade/debug (item 30). None se não roda mais
    (one-shot já executado). interval: last_run+período (ou agora se nunca rodou). cron: próximo
    minuto que casa. once: o alvo (None se já rodou)."""
    s = parse_schedule(schedule)
    if s["kind"] == "interval":
        return now if last_run is None else last_run + s["seconds"]
    if s["kind"] == "once":
        target = _parse_iso(s["at"])
        return None if last_run is not None else target
    if s["kind"] == "cron":
        # varre minuto a minuto a partir do próximo minuto cheio (cap ~366 dias).
        start = int(now // 60 + 1) * 60
        for k in range(0, 366 * 24 * 60):
            t = start + k * 60
            if _cron_match(s["expr"], datetime.fromtimestamp(t)):
                return float(t)
        return None
    return None


def run_script(cmd: str, *, cwd: str = ".", timeout: float = 120.0) -> str:
    """Job SCRIPT (item 30): roda um comando do OPERADOR (config confiável) e devolve o stdout — sem
    gastar LLM. exit ≠0 vira texto informativo. Env sanitizado, teto de saída."""
    import subprocess
    from okami.core.tools import sanitized_env
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,  # nosec B602
                           text=True, timeout=timeout, env=sanitized_env())  # nosemgrep — script do operador
    except subprocess.TimeoutExpired:
        return f"[script] timeout ({timeout}s): {cmd[:80]}"
    except Exception as e:  # noqa: BLE001
        return f"[script] erro ao rodar: {e}"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    out = out[:50_000]
    if r.returncode != 0:
        return f"[script exit={r.returncode}] {out or '(sem saída)'}"
    return out or "(script sem saída)"


def delivery_targets(target, home: str = "") -> list[str]:
    """Alvos de entrega de um job: `target` aceita VÁRIOS chats separados por vírgula (estilo Hermes
    deliver=\"telegram,slack\"); sem alvo cai na CASA (/sethome); sem casa → ninguém (só registro)."""
    raw = [t.strip() for t in str(target or "").split(",") if t.strip()]
    if not raw:
        return [home] if home else []
    out: list[str] = []
    for t in raw:                                    # dedup preservando a ordem
        if t not in out:
            out.append(t)
    return out


def delivery_decision(result: str) -> tuple[bool, str]:
    """Decide se a saída de um job vai pro chat. Marcador de silêncio (NO_REPLY/SILENT/[SILENT]/NO REPLY,
    estilo Hermes) é salvo/registrado mas NÃO entregue — corta o spam de cron 'sem novidade'. Devolve
    (entregar, texto). #11: detector multi-marcador compartilhado em vez de só `[SILENT]`."""
    from okami.gateway.silence import is_intentional_silence, strip_silence_prefix
    s = result or ""
    if is_intentional_silence(s):                    # só o marcador → não entrega, sem texto
        return False, ""
    stripped = strip_silence_prefix(s)
    if stripped != s.strip():                        # '[SILENT] nota interna' → não entrega, guarda a nota
        return False, stripped
    return True, s


class Scheduler:
    def __init__(self, root: str = ".", *, clock=time.time):
        self.path = Path(root) / ".okami" / "cron.json"
        self._clock = clock

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, jobs: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)

    def _atomic(self, mutate):
        """load → mutate(jobs) → save, SOB _FileLock cross-processo. Sem isto, a thread do scheduler
        (tick→mark_run) e o CLI (add/remove/toggle) carregam o MESMO cron.json, alteram em memória e
        salvam — o último save sobrescreve o do outro (last_run perdido → job re-executa ou some).
        `mutate` muta a lista in-place e/ou devolve (nova_lista, resultado); só-resultado mantém in-place."""
        from okami.core.filelock import _FileLock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(self.path):
            jobs = self.load()
            ret = mutate(jobs)
            new_jobs, result = ret if isinstance(ret, tuple) else (jobs, ret)
            self.save(new_jobs)
            return result

    def add(self, schedule: str, prompt: str, agent: str | None = None, target: str | None = None,
            action: str | None = None, gate: str | None = None, script: str | None = None) -> dict:
        def _m(jobs):
            base = _slug(prompt)
            jid, i = base, 2
            ids = {j["id"] for j in jobs}
            while jid in ids:                        # unicidade do id checada DENTRO do lock (sem corrida)
                jid, i = f"{base}-{i}", i + 1
            job = {"id": jid, "schedule": schedule, "kind": parse_schedule(schedule)["kind"],
                   "prompt": prompt, "agent": agent, "target": target, "enabled": True, "last_run": None}
            if action:                               # ação INTERNA (ex.: 'curator') em vez de prompt p/ o harness
                job["action"] = action
            if gate:                                 # wake-gate: comando barato decide se ACORDA o agente
                job["gate"] = gate
            if script:                               # job SCRIPT: roda comando e entrega stdout (sem LLM)
                job["script"] = script
            jobs.append(job)
            return (jobs, job)
        return self._atomic(_m)

    # ----------------------------------------------------------------- histórico de output (item 30)
    def _output_dir(self, jid: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(jid)) or "job"
        return self.path.parent / "cron" / "output" / safe

    def record_output(self, jid: str, text: str, *, now_ts: float | None = None) -> None:
        """Persiste o resultado de uma execução do job (.okami/cron/output/<id>/<ts>.md), rotativo.
        Sem isto o resultado some após entregar — não dava p/ ver 'o que o job de ontem achou'."""
        now = now_ts if now_ts is not None else self._clock()
        d = self._output_dir(jid)
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{int(now * 1000)}.md").write_text(str(text or ""), encoding="utf-8")
            for old in sorted(d.glob("*.md"))[:-20]:     # mantém os 20 mais recentes
                old.unlink(missing_ok=True)
        except OSError:
            pass

    def output_history(self, jid: str, limit: int = 10) -> list[dict]:
        """Execuções recentes do job: [{ts, text}], mais nova primeiro."""
        d = self._output_dir(jid)
        if not d.exists():
            return []
        out = []
        for p in sorted(d.glob("*.md"), reverse=True)[:limit]:
            try:
                ts = int(p.stem) / 1000.0
            except ValueError:
                ts = 0.0
            out.append({"ts": ts, "text": p.read_text(encoding="utf-8", errors="ignore")})
        return out

    def remove(self, jid: str) -> bool:
        def _m(jobs):
            kept = [j for j in jobs if j["id"] != jid]
            return (kept, len(kept) != len(jobs))
        return self._atomic(_m)

    def set_enabled(self, jid: str, on: bool) -> None:
        def _m(jobs):
            for j in jobs:
                if j["id"] == jid:
                    j["enabled"] = on
        self._atomic(_m)

    def due(self, now_ts: float | None = None) -> list[dict]:
        now = now_ts if now_ts is not None else self._clock()
        return [j for j in self.load() if j.get("enabled", True)
                and is_due(j["schedule"], now, j.get("last_run"))]

    def mark_run(self, jid: str, now_ts: float | None = None) -> None:
        now = now_ts if now_ts is not None else self._clock()

        def _m(jobs):
            for j in jobs:
                if j["id"] == jid:
                    j["last_run"] = now
                    if j.get("kind") == "once":
                        j["enabled"] = False     # one-shot: desativa após rodar
        self._atomic(_m)

    def tick(self, execute, now_ts: float | None = None) -> list[tuple[str, str]]:
        """Roda os jobs vencidos via `execute(job)->str`; marca cada um. Devolve [(id, resultado)]."""
        now = now_ts if now_ts is not None else self._clock()
        out = []
        for job in self.due(now):
            try:
                result = execute(job)
            except Exception as e:  # noqa: BLE001 — um job ruim não derruba o scheduler
                result = f"erro: {e}"
            self.mark_run(job["id"], now)
            out.append((job["id"], result))
        return out
