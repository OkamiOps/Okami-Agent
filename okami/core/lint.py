"""Lint de POSTURA (#12) — `okami doctor --lint` / `okami policy check`, no estilo OpenClaw conformance.

Não testa "a config carrega" (isso é o doctor). Testa se a POSTURA é segura p/ produto/exposição:
aprovação, segredo versionado, isolamento do sandbox, allowlist de canal, trust de MCP, perms do
.env, exposição do gateway. Cada achado tem nível pass | warn | fail e uma dica de conserto.
`okami policy check` falha (exit≠0) se houver QUALQUER fail — bom p/ CI/pre-deploy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    check: str
    level: str          # pass | warn | fail
    message: str
    fix: str = ""


_SECRET_LEAF = re.compile(r"api[_-]?key|apikey|token|secret|passwo?rd|credential|private[_-]?key|authorization",
                          re.IGNORECASE)
# sufixos que parecem segredo mas NÃO são o valor: nome de env var, URL, id, caminho…
_NOT_SECRET_SUFFIX = ("_env", "_url", "_uri", "_endpoint", "_id", "_name", "_path", "_file", "_header")


def _is_secret_leaf(leaf: str) -> bool:
    low = leaf.lower()
    if low.endswith(_NOT_SECRET_SUFFIX):
        return False                                  # *_env (nome), *_url (endpoint), … → não é o segredo
    return bool(_SECRET_LEAF.search(low))


def _looks_real_secret(value: str) -> bool:
    """Distingue um SEGREDO real (sk-…, JWT, token longo) de um dummy/local ('lm-studio', 'not-needed')."""
    from okami.core.redact import redact
    v = value.strip()
    if redact(v) != v:                                # bate um padrão conhecido (sk-/JWT/AKIA/ghp_/xox/Bearer)
        return True
    return len(v) >= 16 and bool(re.search(r"[A-Za-z]", v) and re.search(r"[0-9]", v))   # longo + alfanumérico


def _scan_secret_literals(node, path="") -> list[tuple[str, str]]:
    """(caminho, valor) de chaves sensíveis com valor LITERAL (não ${ENV}) — segredo em texto."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            kp = f"{path}.{k}" if path else str(k)
            if isinstance(v, (dict, list)):
                out += _scan_secret_literals(v, kp)
            elif _is_secret_leaf(str(k)) and isinstance(v, str) and v.strip() and not v.strip().startswith("${"):
                out.append((kp, v))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _scan_secret_literals(v, f"{path}[{i}]")
    return out


def lint_posture(cfg, *, base_yaml: Path | None = None, env_path: Path | None = None) -> list[Finding]:
    """Roda os checks de postura sobre a config carregada. `base_yaml` = okami.yaml versionável."""
    f: list[Finding] = []

    # 1) aprovação ------------------------------------------------------------
    mode = (getattr(cfg, "approvals", None) or {}).get("mode", "manual")
    if mode == "yolo":
        f.append(Finding("approvals.mode", "fail", "approvals.mode=yolo → auto-aprova TUDO (sem go/no-go).",
                         "use manual ou smart; yolo só por sessão (/yolo)."))
    elif mode == "off":
        f.append(Finding("approvals.mode", "warn", "approvals.mode=off → nega sensível (fail-closed), mas sem "
                         "supervisão humana.", "manual/smart se houver alguém p/ aprovar."))
    else:
        f.append(Finding("approvals.mode", "pass", f"approvals.mode={mode}."))

    # 2) segredo em texto no YAML VERSIONÁVEL ---------------------------------
    base = base_yaml or Path("okami.yaml")
    if base.exists():
        try:
            import yaml as _yaml
            raw_base = _yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            raw_base = {}
        leaks = _scan_secret_literals(raw_base)
        real = [p for p, v in leaks if _looks_real_secret(v)]
        dummy = [p for p, v in leaks if not _looks_real_secret(v)]
        if real:
            f.append(Finding("secrets.in_yaml", "fail",
                             f"segredo REAL em texto no {base.name} (versionável): {', '.join(real[:5])}.",
                             "mova p/ .env e referencie com ${ENV_VAR}."))
        elif dummy:
            f.append(Finding("secrets.in_yaml", "warn",
                             f"valor literal em chave sensível no {base.name}: {', '.join(dummy[:5])} "
                             "(parece dummy/local — confirme que não é segredo real).",
                             "se for segredo, use ${ENV_VAR}; se for dummy local, ok."))
        else:
            f.append(Finding("secrets.in_yaml", "pass", f"sem segredo literal no {base.name}."))

    # 3) sandbox / isolamento -------------------------------------------------
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(getattr(cfg, "sandbox", None) or {})
    exposed = bool(getattr(cfg, "gateway", None) or {})   # gateway (Telegram/API) = superfície de rede; voz é local
    if sb.effective_backend() == "local" and exposed:
        f.append(Finding("sandbox.backend", "warn", "backend local numa instalação com gateway/superfície exposta "
                         "→ sem isolamento real do shell.", "sandbox.profile: hardened (docker se houver)."))
    elif sb.mode == "yolo":
        f.append(Finding("sandbox.mode", "warn", "sandbox.mode=yolo → sem freios e rede liberada.",
                         "workspace-write no uso normal."))
    else:
        f.append(Finding("sandbox.backend", "pass", f"sandbox backend={sb.backend} mode={sb.mode}."))

    # 4) MCP trust store ------------------------------------------------------
    for name, conf in (getattr(cfg, "mcp", None) or {}).items():
        conf = conf or {}
        if conf.get("trusted") or str(conf.get("trust", "")).lower() == "trusted":
            f.append(Finding(f"mcp.{name}.trust", "warn", f"MCP '{name}' trust=trusted → bypassa o go/no-go por "
                             "capability.", "use reviewed + manifesto por-tool se não for 100% confiável."))
        url = conf.get("url", "")
        if url.startswith("http://") and conf.get("insecure"):
            f.append(Finding(f"mcp.{name}.url", "fail", f"MCP '{name}' http remoto com insecure:true (plaintext).",
                             "use https:// ou um servidor local."))
        for hk, hv in (conf.get("headers") or {}).items():
            if isinstance(hv, str) and len(hv) > 8 and not hv.strip().startswith("${"):
                f.append(Finding(f"mcp.{name}.headers", "fail", f"MCP '{name}' header {hk} com segredo literal.",
                                 "use ${ENV_VAR}."))

    # 5) perms do .env --------------------------------------------------------
    from okami.config import global_env_path
    genv = env_path or global_env_path()
    if genv and Path(genv).exists():
        import stat as _stat
        mode_bits = _stat.S_IMODE(Path(genv).stat().st_mode)
        if mode_bits & 0o077:
            f.append(Finding("env.perms", "warn", f"{Path(genv).name} com perms {oct(mode_bits)} (legível p/ outros).",
                             "okami doctor --fix (chmod 600)."))
        else:
            f.append(Finding("env.perms", "pass", ".env 0600."))

    # 6) exposição do gateway -------------------------------------------------
    gw = getattr(cfg, "gateway", None) or {}
    host = str(gw.get("host", "")).strip()
    if host in ("0.0.0.0", "::"):
        import os
        has_token = bool(os.getenv("OKAMI_API_TOKEN"))
        lvl = "warn" if has_token else "fail"
        f.append(Finding("gateway.exposure", lvl, f"gateway bind {host} (exposto à rede)"
                         + ("" if has_token else " SEM OKAMI_API_TOKEN."),
                         "bind 127.0.0.1, ou exija OKAMI_API_TOKEN + rede privada."))

    return f


def summarize(findings: list[Finding]) -> dict:
    """Contagem por nível + pior nível (p/ exit code / status --json)."""
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for x in findings:
        counts[x.level] = counts.get(x.level, 0) + 1
    worst = "fail" if counts["fail"] else ("warn" if counts["warn"] else "pass")
    return {"counts": counts, "worst": worst, "ok": counts["fail"] == 0}
