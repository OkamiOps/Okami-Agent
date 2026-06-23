"""Reduz ERRO de edição (paridade Hermes #31): o modelo copia aspa curva/travessão/nbsp que NÃO casa
byte-a-byte com a aspa reta/hífen do arquivo → edição falhava. Agora o fuzzy normaliza unicode→ASCII."""
from __future__ import annotations

from okami.core.tools import EditFile, ToolContext


def test_edit_matches_smart_quotes_and_dash(tmp_path):
    (tmp_path / "a.txt").write_text('Use "aspas" e - hifen aqui\n', encoding="utf-8")   # RETO no arquivo
    ctx = ToolContext(workspace=tmp_path, read_files={"a.txt"})
    # old com aspas CURVAS (“ ”) e travessão EM-DASH (—) — o modelo copiou "bonito"
    res = EditFile().run(
        {"path": "a.txt", "old": "Use “aspas” e — hifen aqui", "new": "TROCADO"}, ctx)
    assert res.ok, res.output
    assert "TROCADO" in (tmp_path / "a.txt").read_text(encoding="utf-8")


def test_edit_matches_nbsp(tmp_path):
    (tmp_path / "b.txt").write_text("a b c\n", encoding="utf-8")           # espaço normal
    ctx = ToolContext(workspace=tmp_path, read_files={"b.txt"})
    res = EditFile().run({"path": "b.txt", "old": "a b c", "new": "x"}, ctx)   # nbsp no old
    assert res.ok, res.output
    assert (tmp_path / "b.txt").read_text(encoding="utf-8").strip() == "x"
