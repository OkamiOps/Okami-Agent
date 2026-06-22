"""Caça it.6 (verificada adversarialmente): scheduler atômico sob concorrência; curator não grava plano
inválido; recall não colapsa por prefixo; recent não some sob expiração; tuning exige amostra; browser
refs por-thread. Os FPs (gateway dedup/coalesce, plugin-hook, i18n, perf de memória) ficaram de fora."""
from __future__ import annotations

import threading


# ---------------------------------------------------------------- #3/#4/#5 scheduler atomicidade
def test_scheduler_mark_run_concurrent_no_state_loss(tmp_path):
    from okami.automation.scheduler import Scheduler
    s = Scheduler(str(tmp_path), clock=lambda: 5000.0)
    ids = [s.add("1h", f"job {i}")["id"] for i in range(12)]

    def mark(jid):
        s.mark_run(jid, 5000.0)

    threads = [threading.Thread(target=mark, args=(j,)) for j in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    jobs = {j["id"]: j for j in s.load()}                # nenhum mark_run sobrescrito pelo outro
    assert all(jobs[j]["last_run"] == 5000.0 for j in ids), \
        [j for j in ids if jobs[j]["last_run"] is None]


# ---------------------------------------------------------------- #2 curator fail-closed
def _skill(root, name):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\norigin: agent\n---\n## Quando\nx\n## Como\ny\n", encoding="utf-8")


def test_validate_plan_drops_invalid_keeps_valid(tmp_path):
    from okami.learning import curator as cur
    _skill(tmp_path, "aaa")
    _skill(tmp_path, "bbb")
    plan = {"merges": [
        {"umbrella": "Bad Name!", "absorb": ["aaa"], "body": "x" * 40},      # umbrella inválida
        {"umbrella": "boa-umbrella", "absorb": ["bbb"], "body": "y" * 40},   # válido
    ], "archive": ["nao-existe"]}                                            # skill inexistente
    norm, errors = cur.validate_plan(plan, tmp_path)
    assert errors                                                            # erros registrados
    assert [m["umbrella"] for m in norm["merges"]] == ["boa-umbrella"]       # inválido NÃO entra
    assert norm["archive"] == []                                            # archive inexistente NÃO entra


# ---------------------------------------------------------------- #9 scoped recall sem colapso por prefixo
def test_scoped_recall_keeps_items_sharing_120char_prefix(tmp_path):
    from okami.memory.base import MemoryItem
    from okami.memory.scoped import ScopedMemory
    from okami.memory.sqlite_fts5 import SqliteFTS5Memory
    proj = SqliteFTS5Memory(tmp_path / "p.db", clock=lambda: 1000.0)
    glob = SqliteFTS5Memory(tmp_path / "g.db", clock=lambda: 1000.0)
    sm = ScopedMemory(proj, glob)
    prefix = "alpha " * 25                                                   # ~150 chars, 120 iniciais iguais
    sm.write(MemoryItem(text=prefix + "FINAL_A", scope="workspace", ts=1000.0))
    sm.write(MemoryItem(text=prefix + "FINAL_B", scope="global", ts=1000.0))
    got = {it.text for it in sm.recall("alpha", limit=5)}
    assert any("FINAL_A" in t for t in got) and any("FINAL_B" in t for t in got)  # os dois sobrevivem


# ---------------------------------------------------------------- #10 recent sob expiração pesada
def test_recent_returns_limit_despite_expired(tmp_path):
    from okami.memory.base import MemoryItem
    from okami.memory.sqlite_fts5 import SqliteFTS5Memory
    now = 1000.0
    m = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: now)
    for i in range(5):
        m.write(MemoryItem(text=f"valido {i}", ts=now))                     # nunca expira (antigos)
    for i in range(20):
        m.write(MemoryItem(text=f"expirado {i}", ts=now, expires_at=now - 1))  # já expirados (recentes)
    got = m.recent(limit=5)
    assert len(got) == 5 and all("valido" in it.text for it in got)         # não devolve <5


# #14 (amostra de tuning) foi REVERTIDO: 3 runs a 100% de violação é sinal deliberado p/ adaptar
# rápido modelo local fraco — comportamento intencional documentado em test_learning.py, não bug.


# ---------------------------------------------------------------- #7 browser refs por-thread
def test_browser_refs_are_thread_local():
    from okami.integrations import browser
    browser._last_refs().clear()
    browser._last_refs()[1] = {"role": "button", "name": "main"}
    other: dict = {}

    def worker():
        other["seen"] = dict(browser._last_refs())                          # thread nova → dict isolado
        browser._last_refs()[2] = {"role": "link", "name": "thread"}

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert other["seen"] == {}                                              # não viu o ref da main
    assert 2 not in browser._last_refs()                                    # main não vê o da outra thread
    assert browser._last_refs()[1]["name"] == "main"                        # main mantém o seu
