"""O prompt PRECISA anunciar o nível de acesso a arquivos — senão o modelo se acha preso.

Bug real (Minerva): `okami fs full` estava aplicado (open_fs=True chegava no ToolContext),
mas o system prompt só falava do workspace → o modelo RECUSAVA mexer fora ("só escrevo no
meu workspace") sem nem tentar. Capacidade sem anúncio = capacidade que não existe.
"""
from __future__ import annotations

from okami.core.harness.prompt import build_system_prompt
from okami.core.harness.models import Task


def test_open_fs_announced_in_prompt(tmp_path):
    p = build_system_prompt(Task(goal="organiza"), {}, workspace=tmp_path, open_fs=True)
    assert "ACESSO TOTAL" in p
    assert "absoluto" in p.lower()


def test_default_jail_not_announced_as_open(tmp_path):
    p = build_system_prompt(Task(goal="x"), {}, workspace=tmp_path)
    assert "ACESSO TOTAL" not in p


def test_allow_paths_still_announced(tmp_path):
    p = build_system_prompt(Task(goal="x"), {}, workspace=tmp_path, allow_paths=["/Users/m"])
    assert "PASTAS EXTRAS" in p


def test_open_fs_wins_over_allow_paths(tmp_path):
    # fs: home seta allow_paths=[~]; fs: full seta open_fs — full não deve listar "extras" confusos
    p = build_system_prompt(Task(goal="x"), {}, workspace=tmp_path, open_fs=True,
                            allow_paths=["/Users/m"])
    assert "ACESSO TOTAL" in p
