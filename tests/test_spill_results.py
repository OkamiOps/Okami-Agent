"""Spill-to-file de saída grande de tool (porta do tool_result_storage do Hermes).

Antes: clean_output cortava o MEIO da saída ("…12.000 chars omitidos…") e o conteúdo era
irrecuperável — o modelo tinha que rodar a tool de novo. Agora a íntegra (já redigida) vai
pra .okami/results/ do workspace e o marcador aponta o caminho: o modelo pagina com
read_file(offset/limit) só se precisar.
"""
from __future__ import annotations

from okami.core.harness.prompt import format_observation
from okami.core.tools.base import ToolResult


def test_big_output_spills_to_file(tmp_path):
    big = "linha importante\n" * 2000                      # ~34K chars > head+tail
    obs = format_observation(3, "run_shell", ToolResult(True, big), workspace=tmp_path)
    assert "omitidos" in obs
    files = list((tmp_path / ".okami" / "results").glob("step3-run_shell*.txt"))
    assert files, "íntegra não foi gravada"
    assert files[0].read_text(encoding="utf-8") == big.rstrip("\n") or big in files[0].read_text(encoding="utf-8")
    rel = str(files[0].relative_to(tmp_path))
    assert rel in obs                                       # o caminho aparece na observação
    assert "read_file" in obs                               # ensina a paginar


def test_small_output_does_not_spill(tmp_path):
    obs = format_observation(1, "list_dir", ToolResult(True, "a.txt\nb.txt"), workspace=tmp_path)
    assert "a.txt" in obs
    assert not (tmp_path / ".okami" / "results").exists()


def test_spilled_file_is_redacted(tmp_path):
    big = ("contexto normal\n" * 600) + "OPENAI_API_KEY=sk-proj-Abc123Def456Ghi789Jkl012Mno345\n" + ("fim\n" * 600)
    format_observation(2, "run_shell", ToolResult(True, big), workspace=tmp_path)
    files = list((tmp_path / ".okami" / "results").glob("step2-*.txt"))
    assert files
    assert "sk-proj-Abc123Def456" not in files[0].read_text(encoding="utf-8")   # segredo NÃO vai pro disco


def test_no_workspace_keeps_old_behavior():
    big = "x" * 20000
    obs = format_observation(1, "run_shell", ToolResult(True, big))
    assert "omitidos" in obs                                # trunca como antes, sem crashar
