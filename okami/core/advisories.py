"""Catálogo de advisories de supply-chain (pesquisa #6 item 15, porta do security_advisories do Hermes).

Pacotes Python comprometidos CONHECIDOS (worm Shai-Hulud, typosquats famosos…) checados no BOOT via
`importlib.metadata.version()` — barato (sem rede). Hit aparece no `okami doctor` (e pode disparar
banner). O dono reconhece com `okami doctor --ack <id>` (persiste em ~/.okami/advisories_ack.json) e
para de ser avisado. O catálogo é DADO — 1 entrada por advisory; atualizar = acrescentar à lista.
"""
from __future__ import annotations

import json
from importlib import metadata

# Cada entrada: id · package · versions (comprometidas) · severity · why. Mantido enxuto e factual.
ADVISORIES: list[dict] = [
    # Worm "Shai-Hulud" (set/2025): publicou versões maliciosas de vários pacotes npm/PyPI que roubam
    # tokens. O SDK oficial da Mistral foi um dos vetores no ecossistema Python.
    {"id": "OKAMI-2025-001", "package": "mistralai", "versions": ["2.4.6"], "severity": "critical",
     "why": "versão publicada pelo worm Shai-Hulud (roubo de tokens) — faça downgrade/upgrade já"},
]


def _installed_version(package: str) -> str | None:
    """Versão instalada do pacote, ou None se não instalado. Isolável p/ teste."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — metadata quebrada não pode derrubar o boot
        return None


def _base_version(v: str) -> str:
    """Normaliza '2.4.6+local'/'2.4.6.post1' → '2.4.6' p/ casar com a lista (tolera sufixo de build)."""
    import re
    m = re.match(r"\d+(?:\.\d+)*", str(v or ""))
    return m.group(0) if m else str(v or "")


def _ack_path():
    from okami.home import okami_home
    return okami_home() / "advisories_ack.json"


def _acked() -> set[str]:
    try:
        return set(json.loads(_ack_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def ack(advisory_id: str) -> bool:
    """Reconhece um advisory (para de avisar). Persiste em ~/.okami/advisories_ack.json."""
    acked = _acked()
    acked.add(str(advisory_id))
    try:
        p = _ack_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(acked)), encoding="utf-8")
        return True
    except OSError:
        return False


def detect_compromised(*, include_acked: bool = False) -> list[dict]:
    """Advisories cujo pacote está instalado numa versão comprometida. `include_acked=False` (default)
    omite os já reconhecidos pelo dono. Cada hit = entrada + 'installed'."""
    acked = _acked()
    out = []
    for a in ADVISORIES:
        if not include_acked and a["id"] in acked:
            continue
        v = _installed_version(a["package"])
        if v and _base_version(v) in {_base_version(x) for x in a["versions"]}:
            out.append({**a, "installed": v})
    return out
