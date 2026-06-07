"""`okami skills prune` — poda as skills auto-distiladas de baixo valor (lixo do auto_skill),
preservando as curadas/instaladas. Cobre detecção por marcador (origin) E por assinatura de corpo
(lixo antigo, sem marcador), e o respeito a --dry-run."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def _mk(root, name, body, meta_extra=""):
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: d\n{meta_extra}---\n{body}\n"
    (d / "SKILL.md").write_text(fm, encoding="utf-8")


def _seed(root):
    # curada (fica): sem marcador, corpo normal
    _mk(root, "frontend-shadcn", "# Frontend\nUse ShadCN.\n")
    # auto NOVA (vai): marcada origin
    _mk(root, "deploy-docker", "# Deploy\n## Como\npassos\n", meta_extra="origin: auto-distilled\n")
    # auto ANTIGA determinística (vai): sem marcador, assinatura do corpo determinístico
    _mk(root, "pasta-okami-agent",
        "# analisa a pasta\n## Como (sequência de tools que funcionou)\nrun_shell → run_shell\n")
    # auto ANTIGA por LLM (vai): sem marcador, template '## Quando usar' + '## Cuidados'
    _mk(root, "apresentacao-amigavel",
        "## Quando usar\nquando cumprimenta\n## Como\nresponda\n## Cuidados\nnão soe robótico\n")


def test_prune_removes_auto_keeps_curated(tmp_path, monkeypatch):
    skroot = tmp_path / "skills"
    skroot.mkdir()
    _seed(skroot)
    monkeypatch.setattr("okami.home.skills_dir", lambda: skroot)

    # dry-run: lista mas NÃO remove
    res = runner.invoke(app, ["skills", "--prune", "--dry-run"])
    assert res.exit_code == 0
    assert "deploy-docker" in res.output and "pasta-okami-agent" in res.output
    assert "frontend-shadcn" not in res.output            # curada não entra na lista
    assert (skroot / "deploy-docker").exists()            # dry-run não apagou

    # real (--yes): remove as três auto (marcador + det + LLM), mantém a curada
    res = runner.invoke(app, ["skills", "--prune", "--yes"])
    assert res.exit_code == 0
    assert (skroot / "frontend-shadcn").exists()
    assert not (skroot / "deploy-docker").exists()
    assert not (skroot / "pasta-okami-agent").exists()
    assert not (skroot / "apresentacao-amigavel").exists()      # LLM-distilada também podada


def test_prune_nothing_when_all_curated(tmp_path, monkeypatch):
    skroot = tmp_path / "skills"
    skroot.mkdir()
    _mk(skroot, "tdd", "# TDD\nteste primeiro\n")
    monkeypatch.setattr("okami.home.skills_dir", lambda: skroot)
    res = runner.invoke(app, ["skills", "--prune", "--yes"])
    assert res.exit_code == 0 and "nada a podar" in res.output
    assert (skroot / "tdd").exists()


def test_prune_bad_names_flag(tmp_path, monkeypatch):
    skroot = tmp_path / "skills"
    skroot.mkdir()
    # nome conversacional ruim, SEM marcador e SEM assinatura de corpo → só cai com --bad-names
    _mk(skroot, "agora-vou-pedir-pra-voce-fazer-uma-coisa-longa", "# x\nconteúdo\n")
    monkeypatch.setattr("okami.home.skills_dir", lambda: skroot)

    res = runner.invoke(app, ["skills", "--prune", "--yes"])      # sem --bad-names: não toca
    assert res.exit_code == 0 and "nada a podar" in res.output
    res = runner.invoke(app, ["skills", "--prune", "--bad-names", "--yes"])
    assert res.exit_code == 0 and not (skroot / "agora-vou-pedir-pra-voce-fazer-uma-coisa-longa").exists()
