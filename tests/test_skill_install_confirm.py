"""Governança de install de skill (achado de segurança na caça e2e): a matriz confiança×scan tem 3
estados (auto/confirm/block), mas install_from_source só barrava 'block'. 'confirm' (fonte não-confiável
+ scan MEDIUM, ou community) instalava SILENCIOSAMENTE — sem o dono confirmar. Agora exige confirm=true."""
from __future__ import annotations

import tempfile
from pathlib import Path

from okami.skills.install import install_from_source
from okami.skills.sources import install_decision


def _fake_skill_fetch(name="terceiros"):
    def fetch(source, dest):
        d = Path(dest) / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\nprocedimento ok")
    return fetch


def test_matrix_has_confirm_state():
    # sanity: existe um estado 'confirm' na matriz (senão este bug nem seria possível)
    states = {install_decision(t, v) for t in ("community", "unverified", "trusted")
              for v in ("INFO", "LOW", "MEDIUM", "HIGH")}
    assert "confirm" in states


def test_confirm_source_not_installed_without_confirmation():
    # acha uma combinação trust×verdict que dá 'confirm'
    combo = next(((t, v) for t in ("community", "unverified") for v in ("INFO", "LOW", "MEDIUM")
                  if install_decision(t, v) == "confirm"), None)
    assert combo, "sem combinação 'confirm' p/ testar"
    skills_root = Path(tempfile.mkdtemp())
    res = install_from_source(f"{combo[0]}://x/y", skills_root, Path(tempfile.mkdtemp()),
                              fetch=_fake_skill_fetch())
    if res.decision == "confirm":
        assert res.ok is False and "confirm" in res.reason.lower()        # NÃO instalou sozinho
        assert not list(skills_root.iterdir())                            # nada caiu no catálogo


def test_confirm_true_lets_it_install():
    combo = next(((t, v) for t in ("community", "unverified") for v in ("INFO", "LOW", "MEDIUM")
                  if install_decision(t, v) == "confirm"), None)
    assert combo
    skills_root = Path(tempfile.mkdtemp())
    res = install_from_source(f"{combo[0]}://x/y", skills_root, Path(tempfile.mkdtemp()),
                              fetch=_fake_skill_fetch(), confirm=True)
    if res.decision == "confirm":
        assert res.ok is True and res.installed                           # com confirm=true → instala
