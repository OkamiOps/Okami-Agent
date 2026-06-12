"""Fontes de skills MULTI-FONTE com TIERS de confiança (pesquisa #6 item 11, porta do skills_hub do
Hermes).

Classifica de ONDE vem uma skill (local / GitHub / ClawHub / URL / well-known) e em que TIER de
confiança (builtin > trusted > community > unverified). Taps configuráveis marcam orgs/fontes como
trusted. A MATRIZ confiança×verdict-do-scan decide a política: auto-instalar (confiável + limpo),
confirmar (comunidade), ou BLOQUEAR (qualquer fonte com achado HIGH+ — segurança vence confiança).

Constrói sobre o que já existe (quarentena + scan_path + lockfile com sha256); aqui é a camada de
PROVENIÊNCIA/política que faltava.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Orgs GitHub conhecidas-boas (tap embutido) → trusted. O dono pode somar com add_tap().
_BUILTIN_GITHUB_TAPS = {"anthropics", "openai", "nousresearch", "huggingface", "okamiops"}
_TAPS_FILE = "skill_taps.json"

_TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1, "unverified": 0}
_SEV_RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass(frozen=True)
class SkillSource:
    raw: str
    kind: str            # local | github | clawhub | url | wellknown
    trust: str           # builtin | trusted | community | unverified
    exec_on_fetch: bool  # a busca EXECUTA código (clawhub/npx) ANTES do scan? → exige --allow-exec


def _taps_path():
    from okami.home import okami_home
    return okami_home() / _TAPS_FILE


def list_taps() -> dict:
    """Taps configurados pelo dono (além dos embutidos). {kind: [prefixos]}."""
    try:
        return json.loads(_taps_path().read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def add_tap(kind: str, prefix: str) -> None:
    """Marca uma fonte (ex.: org GitHub) como TRUSTED. Persiste em <home>/skill_taps.json."""
    taps = list_taps()
    lst = taps.setdefault(kind, [])
    if prefix not in lst:
        lst.append(prefix)
    try:
        p = _taps_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(taps, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def remove_tap(kind: str, prefix: str) -> bool:
    taps = list_taps()
    lst = taps.get(kind, [])
    if prefix not in lst:
        return False
    lst.remove(prefix)
    try:
        _taps_path().write_text(json.dumps(taps, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return True


def _github_trust(owner: str) -> str:
    owner_l = owner.lower()
    if owner_l in _BUILTIN_GITHUB_TAPS:
        return "trusted"
    if owner_l in {o.lower() for o in list_taps().get("github", [])}:
        return "trusted"
    return "community"


def classify_source(source: str) -> SkillSource:
    """Classifica a fonte → (kind, trust, exec_on_fetch). Igual ao _fetch_skill_source (local/clawhub/
    owner-repo/url) + tier de confiança + well-known."""
    s = (source or "").strip()
    if Path(s).exists():                              # caminho local = do dono → confiança alta
        return SkillSource(s, "local", "trusted", False)
    if s.startswith("clawhub:"):                      # ClawHub roda npx ANTES do scan
        return SkillSource(s, "clawhub", "community", True)
    if "/.well-known/skills" in s:                    # endpoint well-known (índice de catálogo)
        return SkillSource(s, "wellknown", "community", False)
    if re.match(r"^[\w.-]+/[\w.-]+$", s):             # owner/repo do GitHub
        owner = s.split("/", 1)[0]
        return SkillSource(s, "github", _github_trust(owner), False)
    if s.startswith(("http://", "https://")):
        return SkillSource(s, "url", "unverified", False)
    return SkillSource(s, "url", "unverified", False)


def install_decision(trust: str, verdict_severity: str) -> str:
    """MATRIZ confiança×verdict (Hermes trust×verdict): 'auto' (instala) | 'confirm' (pergunta) |
    'block' (recusa). REGRA DURA: achado HIGH+ → block SEMPRE (segurança vence confiança). Senão:
    builtin/trusted limpo → auto; o resto → confirm."""
    sev = _SEV_RANK.get((verdict_severity or "INFO").upper(), 0)
    if sev >= _SEV_RANK["HIGH"]:
        return "block"
    if _TRUST_RANK.get(trust, 0) >= _TRUST_RANK["trusted"] and sev <= _SEV_RANK["LOW"]:
        return "auto"
    return "confirm"


def fetch_wellknown(base_url: str, *, http=None) -> list[dict]:
    """Busca o índice de skills de um endpoint well-known (`<base>/.well-known/skills/index.json`).
    Retorna [{name, source, version?}]. FAIL-OPEN: erro/forma inesperada → []. `http(url)->dict` injetável."""
    url = base_url.rstrip("/")
    if "/.well-known/skills" not in url:
        url = url + "/.well-known/skills/index.json"
    try:
        payload = (http or _http_get_json)(url)
    except Exception:  # noqa: BLE001 — descoberta nunca quebra
        return []
    skills = (payload or {}).get("skills")
    if not isinstance(skills, list):
        return []
    out = []
    for e in skills:
        if isinstance(e, dict) and e.get("name") and e.get("source"):
            out.append({"name": str(e["name"]), "source": str(e["source"]),
                        "version": str(e.get("version", ""))})
    return out


def _http_get_json(url: str, timeout: float = 15.0) -> dict:
    import urllib.request
    from okami.core.net_guard import validate_public_url   # #6 anti-SSRF
    validate_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "okami/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — well-known público, validado
        return json.loads(r.read().decode("utf-8", "ignore")) or {}
