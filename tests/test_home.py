"""Casa do Okami (okami/home.py): resolução de base + migração de ~/skills e ~/agents soltos."""

from __future__ import annotations

from pathlib import Path

from okami import home


def test_okami_home_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "custom"))
    assert home.okami_home() == tmp_path / "custom"
    monkeypatch.delenv("OKAMI_HOME")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert home.okami_home() == tmp_path / ".okami"


def test_base_dir_project_vs_global(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)
    home_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.delenv("OKAMI_HOME", raising=False)

    # SEM projeto → casa global (~/.okami), não o CWD cru
    monkeypatch.chdir(tmp_path)
    assert home.base_dir() == home_dir / ".okami"
    assert home.skills_dir() == home_dir / ".okami" / "skills"
    assert home.agents_dir() == home_dir / ".okami" / "agents"

    # COM projeto (okami.yaml fora da home) → a pasta do projeto
    (proj / "okami.yaml").write_text("default_provider: x\nproviders: {x: {model: m}}\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    assert home.base_dir() == proj
    assert home.agents_dir() == proj / "agents"


def test_base_dir_project_equals_home_falls_to_global(tmp_path, monkeypatch):
    # 'projeto = home' (okami.yaml na própria home) → NÃO espalha na home; vai pra ~/.okami
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OKAMI_HOME", raising=False)
    (tmp_path / "okami.yaml").write_text("default_provider: x\nproviders: {x: {model: m}}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert home.base_dir() == tmp_path / ".okami"


def test_migrate_stray_moves_into_okami_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OKAMI_HOME", raising=False)
    (tmp_path / "skills" / "minha-skill").mkdir(parents=True)
    (tmp_path / "skills" / "minha-skill" / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / "agents" / "okami").mkdir(parents=True)
    moved = home.migrate_stray()
    assert set(moved) == {"skills", "agents"}
    assert (tmp_path / ".okami" / "skills" / "minha-skill" / "SKILL.md").exists()
    assert (tmp_path / ".okami" / "agents" / "okami").exists()
    assert not (tmp_path / "skills").exists() and not (tmp_path / "agents").exists()
    # idempotente: segunda vez não move nada
    assert home.migrate_stray() == []


def test_migrate_skips_when_home_is_a_project(tmp_path, monkeypatch):
    # se a home É um projeto (okami.yaml na home), NÃO mexe nas pastas — são intencionais
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OKAMI_HOME", raising=False)
    (tmp_path / "okami.yaml").write_text("x: 1\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    assert home.migrate_stray() == [] and (tmp_path / "skills").exists()


def test_migrate_does_not_clobber_existing_target(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OKAMI_HOME", raising=False)
    (tmp_path / "skills" / "a").mkdir(parents=True)
    (tmp_path / ".okami" / "skills").mkdir(parents=True)   # destino já existe → não move (não clobbera)
    assert home.migrate_stray() == [] and (tmp_path / "skills").exists()
