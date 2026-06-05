"""Config durability (P1.2): escrita atômica + backup rotacionado + recovery de corrompido."""

from __future__ import annotations

import stat

from okami.core.safe_io import read_yaml_resilient, secure_write, secure_write_yaml


def test_secure_write_atomic_chmod_and_lastgood(tmp_path):
    p = tmp_path / "c.yaml"
    secure_write(p, "a: 1\n")
    assert p.read_text(encoding="utf-8") == "a: 1\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o644
    assert (tmp_path / "c.yaml.last-good").exists()
    assert not list(tmp_path.glob(".c.yaml.*tmp*"))         # sem tmp deixado pra trás


def test_backup_rotation(tmp_path):
    p = tmp_path / "c.yaml"
    secure_write(p, "v: 1\n")          # 1ª: não existia → sem backup
    secure_write(p, "v: 2\n")          # current(1) → bak1
    secure_write(p, "v: 3\n")          # bak1→bak2, current(2)→bak1
    assert p.read_text(encoding="utf-8").strip() == "v: 3"
    assert (tmp_path / "c.yaml.bak1").read_text(encoding="utf-8").strip() == "v: 2"
    assert (tmp_path / "c.yaml.bak2").read_text(encoding="utf-8").strip() == "v: 1"


def test_read_resilient_recovers_from_corrupt(tmp_path):
    p = tmp_path / "c.yaml"
    secure_write_yaml(p, {"x": 1, "y": [1, 2]})             # escreve + .last-good
    p.write_text("::: not yaml : : [", encoding="utf-8")    # corrompe o principal
    assert read_yaml_resilient(p) == {"x": 1, "y": [1, 2]}  # recuperou do .last-good


def test_read_resilient_default_when_nothing(tmp_path):
    assert read_yaml_resilient(tmp_path / "none.yaml", default={"d": 1}) == {"d": 1}
