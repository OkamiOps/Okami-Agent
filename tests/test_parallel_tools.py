"""parallel — execução paralela de tools read-only do MESMO lote (pesquisa #7 item 20).

paths_collide: detecta colisão de subtree entre as ações (write/patch que tocam o mesmo lugar
NÃO podem ir em paralelo). run_parallel: ThreadPoolExecutor, resultados na ORDEM DE ENTRADA,
exceção de uma tool embrulhada como o loop (não derruba as outras), wall-clock ~= max (não soma)."""

from __future__ import annotations

import time

from okami.core.harness import parallel
from okami.core.harness.parsing import Action
from okami.core.tools import ToolContext, ToolResult


# ----------------------------------------------------------------- paths_collide
def test_paths_collide_same_file():
    acts = [Action("write_file", {"path": "a.txt"}), Action("read_file", {"path": "a.txt"})]
    assert parallel.paths_collide(acts) is True


def test_paths_collide_subtree():
    # escrever em dir/ e ler dir/x.txt = colisão de subtree
    acts = [Action("write_file", {"path": "pkg"}), Action("read_file", {"path": "pkg/mod.py"})]
    assert parallel.paths_collide(acts) is True


def test_paths_collide_disjoint():
    acts = [Action("read_file", {"path": "a.txt"}), Action("read_file", {"path": "b.txt"})]
    assert parallel.paths_collide(acts) is False


def test_paths_collide_apply_patch_uses_patch_paths():
    patch = "*** Begin Patch\n*** Update File: shared.py\n@@\n-x\n+y\n*** End Patch"
    acts = [Action("apply_patch", {"patch": patch}), Action("read_file", {"path": "shared.py"})]
    assert parallel.paths_collide(acts) is True


def test_paths_collide_no_path_actions():
    acts = [Action("run_shell", {"cmd": "ls"}), Action("read_file", {"path": "a.txt"})]
    # run_shell sem path-arg não colide com nada por path
    assert parallel.paths_collide(acts) is False


# ----------------------------------------------------------------- run_parallel
class _SleepTool:
    """Tool stub que dorme `secs` e devolve uma marca — wall-clock prova o paralelismo."""

    def __init__(self, secs, mark):
        self.secs = secs
        self.mark = mark

    def run(self, args, ctx):
        time.sleep(self.secs)
        return ToolResult(True, f"out-{self.mark}", False)


class _BoomTool:
    def run(self, args, ctx):
        raise RuntimeError("explodiu")


def test_run_parallel_preserves_input_order(tmp_path):
    registry = {"t0": _SleepTool(0.05, "0"), "t1": _SleepTool(0.01, "1"), "t2": _SleepTool(0.03, "2")}
    acts = [Action("t0", {}), Action("t1", {}), Action("t2", {})]
    ctx = ToolContext(workspace=tmp_path)
    results = parallel.run_parallel(acts, registry, ctx)
    assert [r.output for r in results] == ["out-0", "out-1", "out-2"]   # ordem de ENTRADA, não de término


def test_run_parallel_wallclock_is_max_not_sum(tmp_path):
    registry = {"slow": _SleepTool(0.2, "s")}
    acts = [Action("slow", {}) for _ in range(4)]      # 4 × 0.2s = 0.8s serial; paralelo ~= 0.2s
    ctx = ToolContext(workspace=tmp_path)
    t0 = time.monotonic()
    results = parallel.run_parallel(acts, registry, ctx, max_workers=8)
    elapsed = time.monotonic() - t0
    assert len(results) == 4
    assert elapsed < 0.6                               # claramente abaixo da soma serial (0.8s)


def test_run_parallel_isolates_exception(tmp_path):
    registry = {"ok": _SleepTool(0.01, "ok"), "boom": _BoomTool()}
    acts = [Action("ok", {}), Action("boom", {}), Action("ok", {})]
    ctx = ToolContext(workspace=tmp_path)
    results = parallel.run_parallel(acts, registry, ctx)
    assert results[0].output == "out-ok"
    assert results[1].ok is False and "explodiu" in results[1].output    # exceção embrulhada como o loop
    assert results[2].output == "out-ok"               # a falha de uma não derruba as outras


# ----------------------------------------------------------------- integração no loop (lote read-only)
def test_loop_runs_readonly_batch_in_parallel(tmp_path):
    """O loop, com um lote LÍDER de leituras, executa via run_parallel e emite cada step em ordem."""
    import json as _json

    from okami.core import Harness, Task

    for n in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / n).write_text(f"conteudo de {n}\n")

    def J(tool, **args):
        return _json.dumps({"tool": tool, "args": args})

    # uma única geração com 3 leituras (multitool) + depois respond
    multi = "```json\n" + J("read_file", path="a.txt") + "\n```\n" \
            "```json\n" + J("read_file", path="b.txt") + "\n```\n" \
            "```json\n" + J("read_file", path="c.txt") + "\n```"

    class Script:
        def __init__(self, outs):
            self.outs = list(outs)

        def __call__(self, messages, schema=None):
            return self.outs.pop(0) if self.outs else "```json\n" + J("respond", message="li tudo") + "\n```"

    t = Task(goal="lê os três arquivos")
    Harness(Script([multi]), t, tmp_path).run()
    # os três reads viraram steps (em ordem determinística)
    read_steps = [s for s in t.steps if s.tool == "read_file"]
    assert [s.args["path"] for s in read_steps] == ["a.txt", "b.txt", "c.txt"]
