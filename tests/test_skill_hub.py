"""Hub de skills: gestão local com PROVENIÊNCIA (list/verify/remove) reusando o lockfile. Liga o
verify() que estava dormente — detecta skill adulterada no disco. (install = `okami learn`; update
re-busca da fonte registrada — a parte de rede fica no CLI, aqui é a contabilidade do lockfile.)"""

from __future__ import annotations

from okami.skills import hub
from okami.skills.lockfile import record


def _mk_skill(root, name, body="conteudo"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n", encoding="utf-8")
    return d


def test_installed_lists_with_provenance(tmp_path):
    d = _mk_skill(tmp_path, "deploy-flow")
    record(tmp_path, "deploy-flow", source="owner/repo", skill_dir=d, version="1.0")
    items = hub.installed(tmp_path, tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it["name"] == "deploy-flow" and it["source"] == "owner/repo"
    assert it["present"] is True and it["ok"] is True


def test_verify_detects_tampering(tmp_path):
    d = _mk_skill(tmp_path, "s1")
    record(tmp_path, "s1", source="x", skill_dir=d)
    (d / "SKILL.md").write_text("---\nname: s1\n---\nADULTERADO\n", encoding="utf-8")  # mudou no disco
    items = hub.installed(tmp_path, tmp_path)
    assert items[0]["ok"] is False                         # hash não bate → adulteração flagrada


def test_missing_dir_marked_absent(tmp_path):
    d = _mk_skill(tmp_path, "sumida")
    record(tmp_path, "sumida", source="x", skill_dir=d)
    import shutil
    shutil.rmtree(d)                                       # registrada no lock mas some do disco
    items = hub.installed(tmp_path, tmp_path)
    assert items[0]["present"] is False and items[0]["ok"] is False


def test_remove_drops_dir_and_lock_entry(tmp_path):
    d = _mk_skill(tmp_path, "velha")
    record(tmp_path, "velha", source="x", skill_dir=d)
    assert hub.remove(tmp_path, tmp_path, "velha") is True
    assert not d.exists()
    assert hub.installed(tmp_path, tmp_path) == []         # saiu do lockfile também


def test_remove_unknown_returns_false(tmp_path):
    assert hub.remove(tmp_path, tmp_path, "nao-existe") is False


def test_installed_empty_when_no_lock(tmp_path):
    assert hub.installed(tmp_path, tmp_path) == []


# ----------------------------------------------------------------- CLI: okami skill list/verify/remove
def test_cli_skill_list_and_remove(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from okami.cli import app
    monkeypatch.setattr("okami.home.skills_dir", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    d = _mk_skill(tmp_path, "minha")
    record(tmp_path, "minha", source="owner/repo", skill_dir=d, version="2.0")
    runner = CliRunner()
    out = runner.invoke(app, ["skill", "list"])
    assert out.exit_code == 0 and "minha" in out.output and "owner/repo" in out.output
    rm = runner.invoke(app, ["skill", "remove", "minha"])
    assert rm.exit_code == 0 and not d.exists()
