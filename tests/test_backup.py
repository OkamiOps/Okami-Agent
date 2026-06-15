"""#9: `okami backup`/`import` — snapshot zipado do HOME (config/memória/sessions/skills/cron) com
SQLite consistente (sqlite3.backup, não cópia torn). Casa com a migração de máquina do dono."""
from __future__ import annotations

import sqlite3
import zipfile


def test_backup_and_restore_roundtrip(tmp_path):
    from okami.core.backup import create_backup, restore_backup
    home = tmp_path / "home"
    (home / "skills" / "x").mkdir(parents=True)
    (home / "okami.yaml").write_text("providers: {}", encoding="utf-8")
    (home / "MEMORY.md").write_text("- fato durável", encoding="utf-8")
    (home / "__pycache__").mkdir()
    (home / "__pycache__" / "junk.pyc").write_text("lixo", encoding="utf-8")
    zp = create_backup(home, tmp_path / "out", stamp="20260616")
    assert zp.exists() and zipfile.is_zipfile(zp)
    home2 = tmp_path / "home2"
    n = restore_backup(zp, home2)
    assert n >= 2
    assert (home2 / "okami.yaml").exists()
    assert (home2 / "MEMORY.md").read_text(encoding="utf-8") == "- fato durável"
    assert not (home2 / "__pycache__").exists()          # cache EXCLUÍDO do backup


def test_backup_snapshots_sqlite_consistently(tmp_path):
    from okami.core.backup import create_backup, restore_backup
    home = tmp_path / "h"
    home.mkdir()
    con = sqlite3.connect(home / "state.db")
    con.execute("create table t(x)")
    con.execute("insert into t values (7)")
    con.commit()
    con.close()
    zp = create_backup(home, tmp_path, stamp="s")
    home2 = tmp_path / "h2"
    restore_backup(zp, home2)
    con = sqlite3.connect(home2 / "state.db")
    assert con.execute("select x from t").fetchone()[0] == 7
    con.close()


def test_restore_rejects_zip_slip(tmp_path):
    # Segurança: um zip malicioso com ../ NÃO pode escrever fora do home.
    from okami.core.backup import restore_backup
    bad = tmp_path / "evil.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escapou.txt", "hack")
    home = tmp_path / "home"
    restore_backup(bad, home)
    assert not (tmp_path / "escapou.txt").exists()       # não escapou do home


def test_restore_chmods_env_0600(tmp_path):
    import os
    from okami.core.backup import create_backup, restore_backup
    home = tmp_path / "h"
    home.mkdir()
    (home / ".env").write_text("OPENAI_API_KEY=x", encoding="utf-8")
    zp = create_backup(home, tmp_path, stamp="s")
    home2 = tmp_path / "h2"
    restore_backup(zp, home2)
    assert oct(os.stat(home2 / ".env").st_mode)[-3:] == "600"   # secret re-chmod 0600
