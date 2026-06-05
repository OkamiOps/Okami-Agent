"""Release-readiness / strict-freshness (#P2): a postura de produção está conforme E verificada no HEAD?

Três sinais, na linguagem do operador:
  • strict green   — a postura VERSIONADA (okami.yaml + okami.policy.yaml) passa `--strict`? (offline, autoritativo)
  • CI green       — o ci.yml passou no commit ATUAL? (via gh, degrada p/ 'desconhecido')
  • strict HEAD ✓  — a conformance estrita foi rodada no HEAD ATUAL? (senão: STALE — re-rode o gate)

A verdade do "strict green" é LOCAL e determinística: avaliamos a postura COMMITADA (ignorando agents/
local — gitignored, não embarca). O gh só responde "isso já foi verificado neste SHA em CI?". Assim o
comando funciona offline (dá o veredito da config) e, com gh, confirma a frescura (stale = HEAD andou
depois do último strict verde).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class WorkflowRun:
    """Último run de um workflow no branch (subset do `gh run list --json`)."""
    conclusion: str | None          # success | failure | cancelled | None (em andamento)
    head_sha: str | None
    status: str | None              # completed | in_progress | queued
    url: str | None = None
    artifact_ok: bool | None = None  # se baixamos o strict-conformance: o summary.ok REAL (gate verdadeiro)


@dataclass
class Readiness:
    head: str | None
    local_strict_ok: bool
    local_summary: dict = field(default_factory=dict)
    local_source: str = ""
    ci: WorkflowRun | None = None
    strict: WorkflowRun | None = None

    # --- sinais derivados (o que o operador lê) ------------------------------
    @property
    def ci_green(self) -> bool | None:
        if self.ci is None:
            return None
        if self.ci.status and self.ci.status != "completed":
            return None
        return self.ci.conclusion == "success"

    @property
    def ci_head_match(self) -> bool | None:
        if self.ci is None or not self.head:
            return None
        return self.ci.head_sha == self.head

    @property
    def strict_head_match(self) -> bool | None:
        if self.strict is None or not self.head:
            return None
        return self.strict.head_sha == self.head

    @property
    def verdict(self) -> str:
        """ready | stale | not_ready | unknown — a regra de prontidão de GA."""
        if not self.local_strict_ok:
            return "not_ready"                         # a config versionada já reprova strict → conserte antes
        # offline (sem gh): a config passa, mas não dá p/ confirmar CI/frescura.
        if self.ci is None and self.strict is None:
            return "unknown"
        # algum run falhou de verdade → não pronto
        if (self.ci and self.ci_green is False) or (self.strict and self.strict.artifact_ok is False):
            return "not_ready"
        # strict rodou, mas num SHA mais velho que o HEAD → frescura perdida
        if self.strict is not None and self.strict_head_match is False:
            return "stale"
        # CI verde no HEAD + strict rodou no HEAD → pronto
        if self.ci_green and self.ci_head_match and self.strict_head_match:
            return "ready"
        return "unknown"

    def signals_ok(self) -> bool:
        """Todos os sinais verdes E frescos (atalho p/ 'pronto p/ release')."""
        return self.verdict == "ready"

    def as_dict(self) -> dict:
        def wf(r: WorkflowRun | None) -> dict | None:
            return None if r is None else {
                "conclusion": r.conclusion, "head_sha": r.head_sha, "status": r.status,
                "url": r.url, "artifact_ok": r.artifact_ok}
        return {
            "head": self.head,
            "verdict": self.verdict,
            "signals": {
                "strict_green": self.local_strict_ok,           # autoritativo (config versionada)
                "ci_green": self.ci_green,
                "ci_head_match": self.ci_head_match,
                "strict_head_match": self.strict_head_match,
            },
            "local": {"summary": self.local_summary, "source": self.local_source},
            "ci": wf(self.ci),
            "strict": wf(self.strict),
        }


# --- coleta dos sinais -------------------------------------------------------

def committed_strict() -> tuple[bool, dict, str]:
    """Avalia `--strict` SÓ sobre a postura VERSIONADA (ignora agents/ local — gitignored, não embarca).

    Devolve (ok, summary, source). Determinístico e offline — é a verdade do 'strict green' para release."""
    from okami.config import load_raw
    from okami.core.lint import summarize
    from okami.core.policy import collect_channels, evaluate, load_policy, strict_policy
    from okami.cli._shared import _load
    raw, _ = load_raw()
    cfg = _load()
    policy, source = load_policy()
    policy = strict_policy(policy)
    channels = collect_channels(raw, agents=None)         # SÓ canais versionados (sem agents/ local)
    findings = evaluate(cfg, policy, raw=raw, channels=channels)
    s = summarize(findings)
    return bool(s["ok"]), s, source


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)  # noqa: S607
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def gh_latest_run(workflow_file: str, branch: str = "main") -> WorkflowRun | None:
    """Último run de um workflow via gh (None se gh ausente/sem auth/offline). Best-effort, nunca lança."""
    try:
        out = subprocess.run(  # noqa: S607
            ["gh", "run", "list", "--workflow", workflow_file, "--branch", branch, "--limit", "1",
             "--json", "conclusion,status,headSha,url"],
            capture_output=True, text=True, timeout=15)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        rows = json.loads(out.stdout)
        if not rows:
            return None
        r = rows[0]
        return WorkflowRun(conclusion=r.get("conclusion"), head_sha=r.get("headSha"),
                           status=r.get("status"), url=r.get("url"))
    except Exception:  # noqa: BLE001
        return None


def collect(*, use_gh: bool = True) -> Readiness:
    """Junta os três sinais. `use_gh=False` = só o veredito local (offline / testes)."""
    ok, summary, source = committed_strict()
    head = git_head()
    ci = gh_latest_run("ci.yml") if use_gh else None
    strict = gh_latest_run("production-conformance.yml") if use_gh else None
    return Readiness(head=head, local_strict_ok=ok, local_summary=summary, local_source=source,
                     ci=ci, strict=strict)


def trigger_strict_enforce(branch: str = "main") -> tuple[bool, str]:
    """Dispara a conformance estrita em modo BLOQUEANTE (enforce=true) no branch. (bool ok, msg)."""
    try:
        out = subprocess.run(  # noqa: S607
            ["gh", "workflow", "run", "production-conformance.yml", "--ref", branch, "-f", "enforce=true"],
            capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return True, "conformance estrita disparada (enforce=true) — acompanhe: okami readiness"
        return False, (out.stderr or out.stdout or "falha ao disparar o workflow").strip()
    except FileNotFoundError:
        return False, "gh não encontrado — instale o GitHub CLI p/ disparar o gate remoto."
    except Exception as e:  # noqa: BLE001
        return False, str(e)
