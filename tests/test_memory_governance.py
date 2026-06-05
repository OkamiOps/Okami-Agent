"""Memória — governança (schema aditivo), escopo/global e auditoria/CRUD (#1/#3/#5/#11)."""

from __future__ import annotations

from okami.memory import MemoryItem, open_memory, open_store
from okami.memory.scoped import ScopedMemory
from okami.memory.sqlite_fts5 import SqliteFTS5Memory


def _mem(tmp_path, now=1000.0, name="m.db"):
    return SqliteFTS5Memory(tmp_path / name, clock=lambda: now)


# ---------------------------------------------------------------- schema aditivo (#1)
def test_governance_fields_persist(tmp_path):
    m = _mem(tmp_path)
    rid = m.write(MemoryItem(text="prefere tema escuro", kind="preference", scope="global", confidence="high"))
    got = next(i for i in m.recent(5) if i.id == rid)
    assert got.scope == "global" and got.confidence == "high" and got.status == "active"


def test_old_db_migrates_additively(tmp_path):
    # simula DB ANTIGO (schema sem as colunas novas) → reabrir deve ALTER e não perder dados
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, text TEXT, kind TEXT, source TEXT, tags TEXT, "
              "ts REAL, importance REAL, last_access REAL, access_count INTEGER, embedding BLOB, "
              "superseded INTEGER DEFAULT 0)")
    c.execute("INSERT INTO items(text, kind, ts, importance) VALUES ('fato antigo', 'fact', 1.0, 0.5)")
    c.commit()
    c.close()
    m = SqliteFTS5Memory(p, clock=lambda: 1000.0)          # reabre → _migrate_columns roda
    items = m.recent(10)
    assert any("fato antigo" in i.text for i in items)     # dado preservado
    assert items[0].scope == "workspace" and items[0].status == "active"   # default das colunas novas


def test_expired_item_drops_from_retrieval(tmp_path):
    now = [1000.0]
    m = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: now[0])
    m.write(MemoryItem(text="tarefa em andamento xyz", kind="fact", expires_at=1500.0))
    m.write(MemoryItem(text="fato duravel abc", kind="fact"))
    assert any("xyz" in i.text for i in m.recent(10))      # antes de expirar, aparece
    now[0] = 2000.0                                         # passou do TTL
    txt = [i.text for i in m.recent(10)]
    assert not any("xyz" in t for t in txt) and any("abc" in t for t in txt)
    assert not any("xyz" in i.text for i in m.recall("tarefa", 10))


def test_supersede_hides_old(tmp_path):
    m = _mem(tmp_path)
    a = m.write(MemoryItem(text="deploy usa heroku"))
    m.write(MemoryItem(text="deploy agora usa vercel", supersedes_id=a))
    txt = [i.text for i in m.recent(10)]
    assert any("vercel" in t for t in txt) and not any("heroku" in t for t in txt)
    assert m.explain(a)["status"] == "superseded"


# ---------------------------------------------------------------- auditoria/CRUD (#5/#11)
def test_crud_forget_archive_and_explain_logs(tmp_path):
    m = _mem(tmp_path)
    a = m.write(MemoryItem(text="o usuario gosta de cafe forte", kind="preference"))
    b = m.write(MemoryItem(text="o projeto usa pytest", kind="fact"))
    m.recall("cafe", 5)                                    # gera retrieval_logs
    info = m.explain(a)
    assert info["id"] == a and info["kind"] == "preference"
    assert info["retrievals"] and info["retrievals"][0]["query"] == "cafe"   # auditoria registrada
    assert m.forget_item(b) is True
    assert not any(i.id == b for i in m.recent(10))        # some do retrieval
    assert m.explain(b)["status"] == "forgotten"           # mas auditável
    assert m.archive_item(a) is True and m.explain(a)["status"] == "archived"
    assert m.forget_item(999999) is False                  # id inexistente


def test_export_dumps_all(tmp_path):
    m = _mem(tmp_path)
    m.write(MemoryItem(text="um", kind="fact"))
    b = m.write(MemoryItem(text="dois", kind="fact"))
    m.forget_item(b)
    dump = m.export()
    assert len(dump) == 2 and {d["text"] for d in dump} == {"um", "dois"}
    forgot = next(d for d in dump if d["text"] == "dois")
    assert forgot["superseded"] is True and forgot["status"] == "forgotten"


# ---------------------------------------------------------------- consolidação (#7)
def test_consolidate_expires_ttl(tmp_path):
    now = [1000.0]
    m = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: now[0])
    m.write(MemoryItem(text="contexto temporario qqq", kind="fact", expires_at=1500.0))
    m.write(MemoryItem(text="fato duravel www", kind="fact"))
    now[0] = 2000.0
    r = m.consolidate()
    assert r["expired"] == 1
    assert m.count() == 1 and any("www" in i.text for i in m.recent(10))


def test_consolidate_merges_near_dups(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)
    a = m.write(MemoryItem(text="usuario prefere tema escuro no editor vscode", kind="preference"))
    b = m.write(MemoryItem(text="usuario prefere tema escuro no editor vscode sempre", kind="preference"))
    assert m.count() == 2
    r = m.consolidate()
    assert r["merged"] == 1 and m.count() == 1           # antigo fundido no novo
    assert m.explain(a)["status"] == "superseded"
    assert m.explain(b)["supersedes_id"] == a            # o novo passou a substituir o antigo


def test_consolidate_keeps_more_confident(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)
    m.write(MemoryItem(text="usuario prefere tema escuro no editor vscode",
                       kind="preference", confidence="high"))
    m.write(MemoryItem(text="usuario prefere tema escuro no editor vscode talvez",
                       kind="preference", confidence="low"))
    r = m.consolidate()
    # o mais novo é fraco (low) e o antigo é forte (high) → NÃO rebaixa o explícito; mantém os dois
    assert r["merged"] == 0 and m.count() == 2


# ---------------------------------------------------------------- escopo/global (#3)
def test_scoped_routes_and_isolates(tmp_path):
    proj = SqliteFTS5Memory(tmp_path / "proj.db", clock=lambda: 1000.0)
    glob = SqliteFTS5Memory(tmp_path / "glob.db", clock=lambda: 1000.0)
    sm = ScopedMemory(proj, glob)
    sm.write(MemoryItem(text="prefere respostas curtas", kind="preference", scope="global"))
    sm.write(MemoryItem(text="este projeto usa fastapi", kind="fact"))     # default = workspace
    assert glob.count() == 1 and proj.count() == 1                          # roteou por escopo
    txt = {i.text for i in sm.recent(10)}
    assert any("curtas" in t for t in txt) and any("fastapi" in t for t in txt)   # lê dos dois
    assert not any("fastapi" in i.text for i in glob.recent(10))            # projeto NÃO contamina a casa


def test_open_memory_global_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    m = open_memory(proj, config={"global": True})
    assert isinstance(m, ScopedMemory)
    m.write(MemoryItem(text="preferencia global zzz", scope="global"))
    m.write(MemoryItem(text="fato do projeto www"))
    m.close()
    # a preferência global foi pra casa (~/.okami), não pro projeto
    g = open_store(tmp_path / "home")
    assert any("zzz" in i.text for i in g.recent(10)) and not any("www" in i.text for i in g.recent(10))


def test_scoped_id_collision_requires_namespace(tmp_path):
    proj = SqliteFTS5Memory(tmp_path / "p.db", clock=lambda: 1.0)
    glob = SqliteFTS5Memory(tmp_path / "g.db", clock=lambda: 1.0)
    pid = proj.write(MemoryItem(text="fato do projeto"))            # id 1
    gid = glob.write(MemoryItem(text="pref global", scope="global"))  # também id 1
    assert pid == gid == 1                                          # COLISÃO de id entre stores
    sm = ScopedMemory(proj, glob)
    assert sm.is_ambiguous(1) and sm.forget_item(1) is False        # id cru ambíguo → NÃO adivinha
    assert sm.explain(1).get("ambiguous") is True
    assert sm.forget_item("global:1") is True                       # namespace resolve a casa
    assert glob.explain(1)["status"] == "forgotten" and proj.explain(1)["status"] == "active"
    assert sm.forget_item("project:1") is True and proj.explain(1)["status"] == "forgotten"


def test_cli_parse_id_namespaces():
    from okami.cli.commands.memory import _parse_id
    assert _parse_id("1", False) == (1, False)
    assert _parse_id("g1", False) == (1, True)            # g1 → casa
    assert _parse_id("global:2", False) == (2, True)
    assert _parse_id("project:3", True) == (3, False)     # namespace vence o --global
    assert _parse_id("#1", True) == (1, True)             # sem prefixo respeita --global


def test_global_not_layered_when_stores_collide(tmp_path, monkeypatch):
    # se o store do projeto e o global apontam pro MESMO diretório, não layer (evita duplicar o arquivo)
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "proj" / ".okami"))
    m = open_memory(tmp_path / "proj", config={"global": True})   # base = proj/.okami == OKAMI_HOME
    assert not isinstance(m, ScopedMemory)


# ---------------------------------------------------------------- CLI
def test_memory_cli_crud(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: x, tier: local}\n", encoding="utf-8")
    r = CliRunner()
    ws = str(tmp_path / "ws")
    assert r.invoke(app, ["memory", "add", "o projeto usa pytest", "-w", ws]).exit_code == 0
    out = r.invoke(app, ["memory", "list", "-w", ws]).output
    assert "#1" in out and "pytest" in out
    ex = r.invoke(app, ["memory", "explain", "1", "-w", ws])
    assert ex.exit_code == 0 and "pytest" in ex.output
    assert r.invoke(app, ["memory", "forget", "1", "-w", ws]).exit_code == 0
    assert "pytest" not in r.invoke(app, ["memory", "list", "-w", ws]).output
    assert r.invoke(app, ["memory", "forget", "999", "-w", ws]).exit_code == 1   # id inexistente
