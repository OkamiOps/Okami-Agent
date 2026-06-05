"""Métricas de memória (#13) — observáveis, integridade e o harness evaluate (com rótulo)."""

from __future__ import annotations

from okami.memory import metrics
from okami.memory.base import MemoryItem
from okami.memory.sqlite_fts5 import SqliteFTS5Memory


def _mem(tmp_path):
    return SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)


def test_stats_composition_and_retrievals(tmp_path):
    m = _mem(tmp_path)
    m.write(MemoryItem(text="prefere tema escuro", kind="preference", scope="global", confidence="high"))
    m.write(MemoryItem(text="o projeto usa fastapi", kind="fact"))
    m.recall("tema escuro", 5)
    st = m.stats()
    assert st["total_active"] == 2
    assert st["by_kind"].get("preference") == 1 and st["by_kind"].get("fact") == 1
    assert st["by_scope"].get("global") == 1 and st["by_confidence"].get("high") == 1
    assert st["retrievals"]["count"] >= 1 and st["retrievals"]["queries"] >= 1


def test_summarize_and_health_in_range(tmp_path):
    m = _mem(tmp_path)
    for i in range(3):
        m.write(MemoryItem(text=f"fato {i} sobre o deploy", kind="fact"))
    m.recall("deploy", 5)
    rep = metrics.report(m)
    assert 0.0 <= rep["health_score"] <= 1.0
    assert rep["observed"]["retrieval_explainability_rate"] == 1.0
    assert rep["observed"]["context_compactness"] >= 0.0


def test_integrity_forget_does_not_leak(tmp_path):
    m = _mem(tmp_path)
    a = m.write(MemoryItem(text="fato a esquecer"))
    m.write(MemoryItem(text="fato que fica"))
    m.forget_item(a)
    integ = metrics.integrity(m)
    assert integ["forget_success_rate"] == 1.0 and integ["leaked_forgotten"] == 0 and integ["inactive_total"] == 1


def test_evaluate_precision_recall_mrr(tmp_path):
    m = _mem(tmp_path)
    m.write(MemoryItem(text="o deploy do app usa vercel", kind="decision"))
    m.write(MemoryItem(text="gosto de cafe pela manha", kind="preference"))
    m.write(MemoryItem(text="uso python no backend", kind="fact"))
    cases = [
        {"query": "onde fica o deploy", "relevant": ["vercel"]},
        {"query": "qual a linguagem do backend", "relevant": ["python"]},
    ]
    res = metrics.evaluate(m, cases, k=3)
    assert res["n_cases"] == 2
    assert res["precision_at_k"] > 0 and res["recall"] > 0 and 0 <= res["mrr"] <= 1
    assert res["precision_weighted_f"] is not None


def test_evaluate_scope_accuracy(tmp_path):
    m = _mem(tmp_path)
    m.write(MemoryItem(text="prefere respostas curtas e diretas", kind="preference", scope="global"))
    res = metrics.evaluate(m, [{"query": "respostas curtas", "scope": "global"}], k=3)
    assert res["scope_accuracy"] == 1.0


def test_memory_stats_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: x, tier: local}\n", encoding="utf-8")
    r = CliRunner()
    ws = str(tmp_path / "ws")
    r.invoke(app, ["memory", "add", "o projeto usa pytest", "-w", ws])
    out = r.invoke(app, ["memory", "stats", "-w", ws]).output
    assert "health" in out and "mem" in out.lower()
    jout = r.invoke(app, ["memory", "stats", "-w", ws, "--json"])
    assert jout.exit_code == 0 and "health_score" in jout.output
