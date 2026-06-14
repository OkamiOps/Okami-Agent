"""TDD da fundação de estado de arquivo (pesquisa #7, item 7).

`record_read` grava o mtime do arquivo no momento da leitura; `check_stale` avisa quando o
arquivo mudou no disco DEPOIS da leitura (alguém/outro processo editou) — base anti-overwrite
cega. Fail-open: sem mtime gravado, ou stat falhando, ele se cala (None) e nunca levanta.
"""
from __future__ import annotations

from okami.core.tools import ToolContext
from okami.core.tools.file_state import check_stale, record_read


def test_record_read_grava_mtime_e_rel(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("oi")
    ctx = ToolContext(workspace=tmp_path)
    record_read(ctx, "a.txt", f)
    assert "a.txt" in ctx.read_files
    assert ctx.read_mtimes["a.txt"] == f.stat().st_mtime


def test_record_read_arquivo_ausente_nao_levanta(tmp_path):
    """Arquivo some entre o read e o record (race) → grava o rel, mas pula o mtime sem explodir."""
    ctx = ToolContext(workspace=tmp_path)
    record_read(ctx, "fantasma.txt", tmp_path / "fantasma.txt")
    assert "fantasma.txt" in ctx.read_files
    assert "fantasma.txt" not in ctx.read_mtimes


def test_check_stale_none_quando_nao_gravado(tmp_path):
    """Fail-open: nunca gravamos o mtime desse rel → não há baseline → None (sem aviso)."""
    f = tmp_path / "a.txt"
    f.write_text("oi")
    ctx = ToolContext(workspace=tmp_path)
    assert check_stale(ctx, "a.txt", f) is None


def test_check_stale_none_quando_inalterado(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("oi")
    ctx = ToolContext(workspace=tmp_path)
    record_read(ctx, "a.txt", f)
    assert check_stale(ctx, "a.txt", f) is None


def test_check_stale_avisa_quando_mtime_muda(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("oi")
    ctx = ToolContext(workspace=tmp_path)
    record_read(ctx, "a.txt", f)
    # força um mtime diferente do gravado (edição externa depois da leitura)
    import os
    novo = f.stat().st_mtime + 100
    os.utime(f, (novo, novo))
    aviso = check_stale(ctx, "a.txt", f)
    assert aviso is not None
    assert "a.txt" in aviso


def test_check_stale_arquivo_ausente_none(tmp_path):
    """stat falha (arquivo apagado) → fail-open: None, sem exceção."""
    f = tmp_path / "a.txt"
    f.write_text("oi")
    ctx = ToolContext(workspace=tmp_path)
    record_read(ctx, "a.txt", f)
    f.unlink()
    assert check_stale(ctx, "a.txt", f) is None
