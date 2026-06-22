"""apply_patch FASE 2 fazia só read_files.add SEM atualizar o baseline de mtime (record_read) — então o
2º patch no MESMO arquivo (fluxo comum: "corrige X e também Y") era recusado como 'mudou no disco' (falso
positivo). write_file/edit_file chamam record_read e não sofrem disso. Achado na caça e2e ampla."""
from __future__ import annotations

import tempfile
from pathlib import Path

from okami.core.tools.base import ToolContext
from okami.core.tools.registry import default_registry

_REG = default_registry()


def _ctx():
    ws = Path(tempfile.mkdtemp())
    return ToolContext(workspace=ws, registry=_REG, open_fs=True), ws


def _patch(path, old, new):
    return f"*** Begin Patch\n*** Update File: {path}\n@@\n-{old}\n+{new}\n*** End Patch"


def test_second_patch_same_file_not_rejected_as_stale():
    ctx, ws = _ctx()
    (ws / "m.py").write_text("a = 1\nb = 2\nc = 3\n")
    _REG["read_file"].run({"path": "m.py"}, ctx)               # leu 1x
    r1 = _REG["apply_patch"].run({"patch": _patch("m.py", "a = 1", "a = 11")}, ctx)
    r2 = _REG["apply_patch"].run({"patch": _patch("m.py", "b = 2", "b = 22")}, ctx)
    assert r1.ok, r1.output
    assert r2.ok, f"2º patch recusado como stale (falso positivo): {r2.output[:120]}"
    assert (ws / "m.py").read_text() == "a = 11\nb = 22\nc = 3\n"   # ambos aplicados


def test_real_external_change_still_detected():
    """Sanidade: o anti-stale continua pegando edição EXTERNA de verdade (não desligamos a proteção)."""
    import time
    ctx, ws = _ctx()
    (ws / "m.py").write_text("x = 1\n")
    _REG["read_file"].run({"path": "m.py"}, ctx)
    time.sleep(0.01)
    (ws / "m.py").write_text("x = 999\n")                      # ALGUÉM mexeu no disco fora do agente
    r = _REG["apply_patch"].run({"patch": _patch("m.py", "x = 1", "x = 2")}, ctx)
    assert not r.ok and "disco" in r.output                    # detecta o drift real
