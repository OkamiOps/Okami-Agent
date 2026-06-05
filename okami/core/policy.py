"""Policy AUTORADA de conformance (#P1.3 — estilo OpenClaw policy.jsonc).

O `doctor --lint` faz checagens de postura embutidas. Isto vai além: uma POLÍTICA declarativa
(`okami.policy.yaml`) que o operador AUTORA p/ governar a instalação — allowlist de provider/modelo,
postura de ingress de canal, teto de trust de MCP, exigência de metadata de tool, retenção, exposição
do gateway. `okami policy check` avalia config+workspace contra ela e produz um ARTEFATO de conformance
(JSON) — bom p/ CI/pre-deploy. Sem o arquivo, vale a baseline DEFAULT_POLICY (segura por padrão).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from okami.core.lint import Finding, lint_posture

# Baseline segura: o que vale quando não há okami.policy.yaml autorado.
DEFAULT_POLICY: dict = {
    "approvals": {"mode_allow": ["manual", "smart"]},      # yolo/off não-conformes por padrão
    "providers": {"allow": None},                          # None = sem allowlist (qualquer provider)
    "models": {"allow": None},                             # globs (fnmatch); None = qualquer modelo
    "channels": {"allow": None, "forbid_open_ingress": True},   # allow_all=true = ingress aberto → fail
    "mcp": {"max_trust": "reviewed"},                      # 'trusted' fica acima do teto
    "secrets": {"forbid_literal_in_yaml": True},
    "gateway": {"require_token": True, "forbid_public_bind": True},
    # backend:local explícito numa instalação exposta = warn; require_isolation_on_exposed = exige Docker real
    "sandbox": {"forbid_forced_local_on_exposed": True, "require_isolation_on_exposed": False},
    "tools": {"require_metadata": True},                   # toda tool com ToolSpec (risk/sensitivity)
    "retention": {"require": False},                       # warn se nada de retenção/quota configurado
}

_TRUST_RANK = {"untrusted": 0, "reviewed": 1, "trusted": 2}

# Postura de PRODUÇÃO/GA (ambiente hostil/público), aplicada por `okami policy check --strict`.
# Endurece o que o default deixa frouxo DE PROPÓSITO p/ dogfood — o default segue dev-friendly
# (sem Docker não quebra a sua máquina). Quem expõe o agente publicamente roda `--strict` no deploy.
PRODUCTION_OVERLAY: dict = {
    "sandbox": {"require_isolation_on_exposed": True},   # exposto SEM isolamento real (Docker) → FAIL
    "retention": {"require": True},                       # exige retenção/quota declarada
    "gateway": {"require_token": True, "forbid_public_bind": True},
    "secrets": {"forbid_literal_in_yaml": True},
    "channels": {"forbid_open_ingress": True},
    "mcp": {"max_trust": "reviewed"},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def strict_policy(policy: dict) -> dict:
    """Aplica a postura de PRODUÇÃO/GA sobre a policy carregada (#P1.2: ativa o modo hostil sob demanda)."""
    return _deep_merge(policy, PRODUCTION_OVERLAY)


def load_policy(path: Path | None = None) -> tuple[dict, str]:
    """Carrega okami.policy.yaml (merge sobre a baseline). Devolve (policy, fonte|'(default)')."""
    candidates = [path] if path else [Path("okami.policy.yaml"), Path("okami.policy.yml"), Path(".okami/policy.yaml")]
    for p in candidates:
        if p and p.exists():
            import yaml as _yaml
            try:
                authored = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                authored = {}
            return _deep_merge(DEFAULT_POLICY, authored), str(p)
    return dict(DEFAULT_POLICY), "(default)"


def collect_channels(raw: dict | None, agents: dict | None = None) -> dict:
    """{(dono, tipo): conf} de canais — bloco global `channels` + canais por-agente (agent.yaml)."""
    out: dict = {}
    for ctype, conf in ((raw or {}).get("channels") or {}).items():
        if isinstance(conf, dict):
            out[("(global)", ctype)] = conf
    for aid, spec in (agents or {}).items():
        chans = (getattr(spec, "raw", None) or {}).get("channels") or {}
        for ctype, conf in chans.items():
            if isinstance(conf, dict):
                out[(aid, ctype)] = conf
    return out


def evaluate(cfg, policy: dict, *, raw: dict | None = None, channels: dict | None = None,
             base_yaml: Path | None = None, env_path: Path | None = None) -> list[Finding]:
    """Avalia config+workspace contra a policy autorada. Inclui a postura embutida do lint."""
    f: list[Finding] = list(lint_posture(cfg, base_yaml=base_yaml, env_path=env_path))

    # approvals.mode_allow ----------------------------------------------------
    allow_modes = (policy.get("approvals") or {}).get("mode_allow")
    mode = (getattr(cfg, "approvals", None) or {}).get("mode", "manual")
    if allow_modes and mode not in allow_modes:
        f.append(Finding("policy.approvals", "fail", f"approvals.mode={mode} fora da policy {allow_modes}.",
                         f"use um de {allow_modes}."))

    # providers.allow ---------------------------------------------------------
    prov_allow = (policy.get("providers") or {}).get("allow")
    providers = getattr(cfg, "providers", None) or {}
    if prov_allow is not None:
        for name in providers:
            if name not in prov_allow:
                f.append(Finding("policy.providers", "fail", f"provider '{name}' não está na allowlist {prov_allow}.",
                                 "remova o provider ou ajuste a policy."))

    # models.allow (globs) ----------------------------------------------------
    model_allow = (policy.get("models") or {}).get("allow")
    if model_allow is not None:
        for name, pc in providers.items():
            model = getattr(pc, "model", "")
            if model and not any(fnmatch.fnmatch(model, g) for g in model_allow):
                f.append(Finding("policy.models", "fail", f"modelo '{model}' ({name}) fora da allowlist {model_allow}.",
                                 "ajuste o model ref ou a policy."))

    # channels: ingress posture ----------------------------------------------
    chpol = policy.get("channels") or {}
    ch_allow = chpol.get("allow")
    for (owner, ctype), conf in (channels or {}).items():
        if ch_allow is not None and ctype not in ch_allow:
            f.append(Finding(f"policy.channels.{ctype}", "fail",
                             f"canal '{ctype}' ({owner}) não está na allowlist {ch_allow}.", "ajuste a policy."))
        if chpol.get("forbid_open_ingress", True) and conf.get("allow_all"):
            f.append(Finding(f"policy.channels.{ctype}.ingress", "fail",
                             f"canal '{ctype}' ({owner}) com allow_all=true → ingress ABERTO.",
                             "use allow_chats: [<ids>] (deny-by-default)."))

    # mcp.max_trust -----------------------------------------------------------
    max_trust = (policy.get("mcp") or {}).get("max_trust", "reviewed")
    from okami.integrations.mcp import _trust_of, servers_of
    for name, conf in servers_of(getattr(cfg, "mcp", None)).items():   # #P1: normaliza mcp.servers.<n>
        lvl = _trust_of(conf or {})
        if _TRUST_RANK.get(lvl, 0) > _TRUST_RANK.get(max_trust, 1):
            f.append(Finding(f"policy.mcp.{name}", "fail", f"MCP '{name}' trust={lvl} acima do teto {max_trust}.",
                             f"baixe p/ {max_trust} (+ manifesto por-tool)."))

    # sandbox: forced local + isolamento exigido em instalação exposta --------
    sbpol = policy.get("sandbox") or {}
    sb = dict(getattr(cfg, "sandbox", None) or {})
    exposed = bool(getattr(cfg, "gateway", None) or {}) or bool(channels)
    if sbpol.get("forbid_forced_local_on_exposed", True) and exposed and sb.get("backend") == "local":
        f.append(Finding("policy.sandbox", "warn", "backend:local EXPLÍCITO numa instalação exposta "
                         "→ desliga o auto-harden por superfície.", "remova o backend fixo ou use profile: hardened."))
    if sbpol.get("require_isolation_on_exposed", False) and exposed:   # #P1.2: ambiente hostil
        from okami.core.sandbox import SandboxPolicy
        strict = bool(SandboxPolicy.from_config(sb).require_isolation) or str(sb.get("profile", "")) == "hardened-strict"
        if not strict:
            f.append(Finding("policy.sandbox.isolation", "fail", "superfície exposta SEM isolamento obrigatório "
                             "→ run_shell/process podem degradar p/ local (sem Docker).",
                             "sandbox.require_isolation: true (ou profile: hardened-strict)."))

    # tools.require_metadata --------------------------------------------------
    if (policy.get("tools") or {}).get("require_metadata", True):
        from okami.core.tool_registry import missing
        from okami.core.tools import default_registry
        drift = missing(default_registry().keys())
        if drift:
            f.append(Finding("policy.tools", "fail", f"tools sem metadata (ToolSpec): {', '.join(drift)}.",
                             "registre em tool_registry.py."))

    # retention ---------------------------------------------------------------
    # Quando a policy EXIGE retenção (strict/produção), ausência é FAIL — não warn. Gateway long-running
    # sem poda incha o disco até morrer; p/ GA isso é bloqueante, não um aviso ignorável.
    if (policy.get("retention") or {}).get("require", False):
        raw_retention = bool((raw or {}).get("retention") or (raw or {}).get("cleanup"))
        if not raw_retention:
            f.append(Finding("policy.retention", "fail", "retenção/quota EXIGIDA mas não declarada (disco "
                             "incha sem limite num gateway long-running).",
                             "declare retention: (sessions/checkpoints/tool_outputs/processes) no okami.yaml "
                             "e operacionalize com cron: okami clean --deep (ver docs/PRODUCTION.md)."))
        else:
            f.append(Finding("policy.retention", "pass", "retenção/quota declarada."))

    return f


def conformance_artifact(findings: list[Finding], *, policy_source: str) -> dict:
    """Artefato de conformance p/ CI/pre-deploy (machine-readable)."""
    from okami.core.lint import summarize
    return {"policy_source": policy_source, "summary": summarize(findings),
            "findings": [vars(x) for x in findings]}


def scaffold() -> str:
    """Texto de um okami.policy.yaml inicial (baseline comentada) p/ `okami policy init`."""
    return (
        "# okami.policy.yaml — política de conformance (autoritativa). Rode: okami policy check\n"
        "approvals:\n  mode_allow: [manual, smart]      # yolo/off reprovam\n"
        "providers:\n  allow: null                      # ex.: [codex, claude, lmstudio]\n"
        "models:\n  allow: null                         # ex.: ['openai-codex/*', 'anthropic/*']\n"
        "channels:\n  allow: null                       # ex.: [telegram]\n  forbid_open_ingress: true   # allow_all=true reprova\n"
        "mcp:\n  max_trust: reviewed                    # 'trusted' fica acima do teto\n"
        "secrets:\n  forbid_literal_in_yaml: true\n"
        "gateway:\n  require_token: true\n  forbid_public_bind: true\n"
        "sandbox:\n  forbid_forced_local_on_exposed: true\n"
        "tools:\n  require_metadata: true\n"
        "retention:\n  require: false                   # true = exige bloco retention/cleanup\n"
    )
