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
