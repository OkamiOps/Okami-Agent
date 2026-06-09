"""Config GLOBAL na casa (~/.okami): um install global (sem projeto no CWD) tem que achar o okami.yaml
da casa de QUALQUER diretório — e os comandos de escrita (setup/config set) gravam lá. Era o bug do
Windows: rodava `okami chat` de um CWD sem okami.yaml e não achava config (find_config só via CWD+ancestrais).
"""
from __future__ import annotations



def test_find_config_falls_back_to_okami_home(tmp_path, monkeypatch):
    home = tmp_path / "okami-home"
    home.mkdir()
    (home / "okami.yaml").write_text("default_provider: x\nproviders: {x: {transport: litellm}}\n", encoding="utf-8")
    monkeypatch.setenv("OKAMI_HOME", str(home))
    empty = tmp_path / "elsewhere"           # CWD sem projeto (install global)
    empty.mkdir()
    from okami.config import find_config
    assert find_config(start=empty) == home / "okami.yaml"


def test_config_dir_is_home_without_project_and_project_when_present(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("OKAMI_HOME", str(home))
    from okami.config import config_dir
    # sem projeto no CWD → escreve na CASA
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    assert config_dir() == home
    # com okami.yaml no CWD → escreve no PROJETO (não na casa)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "okami.yaml").write_text("default_provider: x\nproviders: {x: {}}\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    assert config_dir() == proj


def test_load_raw_reads_local_yaml_next_to_home_config(tmp_path, monkeypatch):
    # o okami.local.yaml tem que ser lido do MESMO lugar do okami.yaml (a casa, no install global).
    home = tmp_path / "okami-home"
    home.mkdir()
    (home / "okami.yaml").write_text("default_provider: x\nproviders: {x: {transport: litellm}}\n", encoding="utf-8")
    (home / "okami.local.yaml").write_text("default_provider: y\n", encoding="utf-8")
    monkeypatch.setenv("OKAMI_HOME", str(home))
    monkeypatch.chdir(tmp_path)               # CWD sem projeto
    if (tmp_path / "okami.yaml").exists():
        (tmp_path / "okami.yaml").unlink()
    from okami.config import load_raw
    raw, path = load_raw()
    assert path == home / "okami.yaml"
    assert raw.get("default_provider") == "y"   # override do okami.local.yaml da casa aplicado
