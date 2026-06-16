"""#10: doctor --fix recupera SQLite malformado (state.db/memória corrompida) — backup + dump/reload."""
from __future__ import annotations

import sqlite3


def test_repair_sqlite_healthy(tmp_path):
    from okami.core.maintenance import repair_sqlite
    db = tmp_path / "ok.db"
    con = sqlite3.connect(db)
    con.execute("create table t(x)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()
    r = repair_sqlite(db)
    assert r["ok"] and r["action"] == "healthy"


def test_repair_sqlite_missing(tmp_path):
    from okami.core.maintenance import repair_sqlite
    assert repair_sqlite(tmp_path / "nope.db")["action"] == "missing"


def test_repair_sqlite_corrupt_backs_up_and_does_not_crash(tmp_path):
    from okami.core.maintenance import repair_sqlite
    db = tmp_path / "bad.db"
    db.write_bytes(b"isto nao eh um banco sqlite valido " * 60)   # não é DB → integrity_check falha
    r = repair_sqlite(db)
    assert r["action"] in ("rebuilt", "failed")                  # tentou; não crashou
    assert any(p.name.startswith("bad.db.malformed-backup") for p in tmp_path.iterdir())  # backup feito


def test_repair_dbs_under_walks_root(tmp_path):
    from okami.core.maintenance import repair_dbs_under
    con = sqlite3.connect(tmp_path / "a.db")
    con.execute("create table t(x)")
    con.commit()
    con.close()
    (tmp_path / "sub").mkdir()
    con2 = sqlite3.connect(tmp_path / "sub" / "b.db")
    con2.execute("create table u(y)")
    con2.commit()
    con2.close()
    results = repair_dbs_under(tmp_path)
    assert {r["action"] for r in results} == {"healthy"} and len(results) == 2
