"""Testes do skill_bundles — bundles de skills (um nome carrega N skills)."""

from __future__ import annotations

from pathlib import Path

import pytest

from okami.skills.bundles import list_bundles, load_bundle


@pytest.fixture()
def bundles_dir(tmp_path: Path) -> Path:
    """Diretório de bundles com um "review.yaml" pronto p/ os testes."""
    d = tmp_path / "bundles"
    d.mkdir()
    (d / "review.yaml").write_text(
        "skills:\n  - code-review\n  - run-tests\n  - git-flow\n",
        encoding="utf-8",
    )
    return d


def test_load_bundle_devolve_a_lista(bundles_dir: Path) -> None:
    assert load_bundle(bundles_dir, "review") == ["code-review", "run-tests", "git-flow"]


def test_list_bundles_inclui_review(bundles_dir: Path) -> None:
    assert "review" in list_bundles(bundles_dir)


def test_load_bundle_inexistente_devolve_vazio(bundles_dir: Path) -> None:
    assert load_bundle(bundles_dir, "inexistente") == []


def test_load_bundle_aceita_str_no_dir(bundles_dir: Path) -> None:
    # Aceita o diretório como str, não só Path.
    assert load_bundle(str(bundles_dir), "review") == ["code-review", "run-tests", "git-flow"]


def test_list_bundles_dir_inexistente_e_vazio(tmp_path: Path) -> None:
    assert list_bundles(tmp_path / "nao-existe") == []


def test_load_bundle_yaml_invalido_e_vazio(tmp_path: Path) -> None:
    # YAML quebrado não deve derrubar o caller — devolve [].
    d = tmp_path / "b"
    d.mkdir()
    (d / "ruim.yaml").write_text("skills: [não-fechado\n  - x\n", encoding="utf-8")
    assert load_bundle(d, "ruim") == []


def test_load_bundle_sem_chave_skills_e_vazio(tmp_path: Path) -> None:
    # Arquivo válido mas sem a chave 'skills' -> [].
    d = tmp_path / "b"
    d.mkdir()
    (d / "vazio.yaml").write_text("outra-chave: 1\n", encoding="utf-8")
    assert load_bundle(d, "vazio") == []


def test_load_bundle_skills_nao_lista_e_vazio(tmp_path: Path) -> None:
    # 'skills' presente mas escalar (não lista) -> [] (fail-safe).
    d = tmp_path / "b"
    d.mkdir()
    (d / "escalar.yaml").write_text("skills: só-uma\n", encoding="utf-8")
    assert load_bundle(d, "escalar") == []


def test_list_bundles_ignora_nao_yaml(tmp_path: Path) -> None:
    d = tmp_path / "b"
    d.mkdir()
    (d / "a.yaml").write_text("skills: []\n", encoding="utf-8")
    (d / "b.yml").write_text("skills: []\n", encoding="utf-8")
    (d / "leia-me.txt").write_text("nada\n", encoding="utf-8")
    nomes = list_bundles(d)
    assert "a" in nomes
    assert "leia-me" not in nomes


def test_list_bundles_ordenado(tmp_path: Path) -> None:
    d = tmp_path / "b"
    d.mkdir()
    for nome in ("zeta", "alfa", "meio"):
        (d / f"{nome}.yaml").write_text("skills: []\n", encoding="utf-8")
    assert list_bundles(d) == sorted(list_bundles(d))


def test_load_bundle_coage_itens_para_str(tmp_path: Path) -> None:
    # Itens não-str (ex.: número) viram str e entradas vazias somem.
    d = tmp_path / "b"
    d.mkdir()
    (d / "mix.yaml").write_text("skills:\n  - code-review\n  - 42\n  - ''\n", encoding="utf-8")
    assert load_bundle(d, "mix") == ["code-review", "42"]
