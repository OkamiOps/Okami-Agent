"""edit_file no-match era um BECO SEM SAÍDA (queixa do dono: agente trava editando código). Hermes,
ao não casar o trecho, mostra a seção PARECIDA ('did you mean') e prescreve a fuga (re-ler / write_file).
Okami só dizia 'trecho não encontrado — precisa ser EXATO' e o modelo re-chutava `old` até o circuit-breaker.
Agora o no-match guia: mostra o trecho mais parecido p/ copiar EXATO + oferece write_file."""
from __future__ import annotations

from okami.core.tools import EditFile, ToolContext


def test_no_match_shows_similar_section_and_escape(tmp_path):
    (tmp_path / "code.py").write_text(
        "def hello():\n    return 'hi'\n\ndef bye():\n    return 'bye'\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    # 'old' com CONTEÚDO errado (não é só whitespace — a linha do corpo diverge de verdade) → não casa nem
    # fuzzy → guia. (Whitespace-só agora casa via fuzzy; ver test_edit_fuzzy.)
    res = EditFile().run(
        {"path": "code.py", "old": "def hello():\n    return 'NOPE'", "new": "def hello():\n    return 'yo'"}, ctx)
    assert res.ok is False
    assert "def hello" in res.output                       # mostra a seção parecida p/ copiar EXATO
    assert "write_file" in res.output.lower()              # oferece a rota de fuga


def test_no_match_with_no_similar_section_still_clean(tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo totalmente diferente\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"a.txt"})
    res = EditFile().run({"path": "a.txt", "old": "xyzzy plugh quux", "new": "z"}, ctx)
    assert res.ok is False and "não encontrado" in res.output.lower()   # sem parecido → erro limpo, não quebra


def test_no_match_shows_top_3_candidates(tmp_path):
    """TOP-3 (paridade Hermes find_closest_lines max_results=3): quando há VÁRIAS funções parecidas com o
    `old` errado, mostra até 3 candidatos — não só o 1º — pra o modelo escolher o certo em vez de ficar
    preso re-chutando um único palpite errado."""
    (tmp_path / "code.py").write_text(
        "def hello_alice():\n    return 'a'\n\n"
        "def hello_bob():\n    return 'b'\n\n"
        "def hello_carol():\n    return 'c'\n\n"
        "def outro():\n    return 'x'\n",
        encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    res = EditFile().run(
        {"path": "code.py", "old": "def hello_XXXXX():\n    return 'zzz'", "new": "def novo(): pass"}, ctx)
    assert res.ok is False
    out = res.output
    assert "hello_alice" in out and "hello_bob" in out and "hello_carol" in out
    assert "3 trechos" in out.lower()


def test_did_you_mean_snippets_have_line_numbers(tmp_path):
    (tmp_path / "code.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    res = EditFile().run(
        {"path": "code.py", "old": "def hello():\n    return 'NOPE'", "new": "x"}, ctx)
    assert res.ok is False
    assert "1: def hello():" in res.output                 # snippet numerado (linha real do arquivo)
