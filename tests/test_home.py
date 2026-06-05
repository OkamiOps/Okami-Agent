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
    (tmp_path / "agents" / "okami" / "agent.yaml").write_text("id: okami\n", encoding="utf-8")  # marcador
    moved = home.migrate_stray()
    assert set(moved) == {"skills", "agents"}
    assert (tmp_path / ".okami" / "skills" / "minha-skill" / "SKILL.md").exists()
    assert (tmp_path / ".okami" / "agents" / "okami" / "agent.yaml").exists()
    assert not (tmp_path / "skills").exists() and not (tmp_path / "agents").exists()
    # idempotente: segunda vez não move nada
    assert home.migrate_stray() == []
    # manifesto auditável do que foi movido
    import json
    manifest = json.loads((tmp_path / ".okami" / "migrations.json").read_text(encoding="utf-8"))
    assert manifest[-1]["moved"] == ["skills", "agents"] or set(manifest[-1]["moved"]) == {"skills", "agents"}
    assert manifest[-1]["from"] == str(tmp_path)


def test_migrate_skips_folders_without_okami_markers(tmp_path, monkeypatch):
    # P1-leve: NÃO sequestra pasta genérica da home — sem SKILL.md / agent.yaml, deixa quieto.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OKAMI_HOME", raising=False)
    (tmp_path / "skills" / "fotos-do-ze").mkdir(parents=True)        # pasta "skills" do usuário, não do Okami
    (tmp_path / "skills" / "fotos-do-ze" / "foto.png").write_text("x", encoding="utf-8")
    (tmp_path / "agents" / "imobiliaria").mkdir(parents=True)         # idem: sem agent.yaml
    assert home.migrate_stray() == []
    assert (tmp_path / "skills" / "fotos-do-ze" / "foto.png").exists()  # intacta
    assert (tmp_path / "agents" / "imobiliaria").exists()
    assert not (tmp_path / ".okami" / "migrations.json").exists()       # nada movido → sem manifesto


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


def test_okami_home_is_single_source_for_env_and_credentials(tmp_path, monkeypatch):
    # P1: OKAMI_HOME custom dirige .env global E credenciais (não mais hardcoded ~/.okami)
    custom = tmp_path / "opt-okami"
    monkeypatch.setenv("OKAMI_HOME", str(custom))
    assert home.env_path() == custom / ".env"
    assert home.credentials_dir() == custom / "credentials"
    assert home.home_path("credentials", "codex.json") == custom / "credentials" / "codex.json"
    # global_env_path() do config delega ao home (fonte única)
    from okami.config import global_env_path
    assert global_env_path() == custom / ".env"


def test_read_path_legacy_fallback(tmp_path, monkeypatch):
    # migração suave: credencial num install LEGADO (~/.okami) ainda é encontrada quando OKAMI_HOME muda
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "novo"))
    legacy = tmp_path / ".okami" / "credentials"
    legacy.mkdir(parents=True)
    (legacy / "codex.json").write_text("{}", encoding="utf-8")
    # atual não existe → cai no legado
    assert home.read_path("credentials", "codex.json") == legacy / "codex.json"
    # quando o atual existe, prefere o atual
    novo = tmp_path / "novo" / "credentials"
    novo.mkdir(parents=True)
    (novo / "codex.json").write_text("{}", encoding="utf-8")
    assert home.read_path("credentials", "codex.json") == novo / "codex.json"
