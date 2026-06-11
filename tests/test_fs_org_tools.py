"""Tools de ORGANIZAÇÃO de arquivos — make_dir / move_path / copy_path / delete_path.

Motivação (bug real): com `okami fs full` a Minerva enxergava ~/Downloads mas não tinha
NENHUMA tool p/ criar pasta ou mover arquivo — read/write/edit não movem binário, e
run_shell é negado no Telegram. Organizar 50 pastas era impossível sem escalar shell.
Estas tools fazem só FS-ops (sem shell), respeitam o jail/_safe_path + denylist de
segredos, e delete é REVERSÍVEL (vai pra lixeira do agente, nunca rm de verdade).
"""
from __future__ import annotations

from okami.core.tools import default_registry
from okami.core.tools.base import ToolContext
from okami.core.tools.files import CopyPath, DeletePath, MakeDir, MovePath


def _ctx(ws, **kw):
    return ToolContext(workspace=ws, **kw)


# ── make_dir ────────────────────────────────────────────────────────────────

def test_make_dir_creates_nested(tmp_path):
    r = MakeDir().run({"path": "a/b/c"}, _ctx(tmp_path))
    assert r.ok, r.output
    assert (tmp_path / "a/b/c").is_dir()


def test_make_dir_existing_is_ok(tmp_path):
    (tmp_path / "x").mkdir()
    assert MakeDir().run({"path": "x"}, _ctx(tmp_path)).ok


def test_make_dir_respects_jail(tmp_path):
    r = MakeDir().run({"path": "../escape"}, _ctx(tmp_path))
    assert not r.ok


# ── move_path ───────────────────────────────────────────────────────────────

def test_move_file(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    r = MovePath().run({"src": "a.txt", "dst": "sub/b.txt"}, _ctx(tmp_path))
    assert r.ok, r.output
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "sub/b.txt").read_text() == "hi"


def test_move_dir_into_dir(tmp_path):
    (tmp_path / "Pasta Velha").mkdir()
    (tmp_path / "Pasta Velha/f.bin").write_bytes(b"\x00\x01")
    r = MovePath().run({"src": "Pasta Velha", "dst": "Arquivo/2024/Pasta Velha"}, _ctx(tmp_path))
    assert r.ok, r.output
    assert (tmp_path / "Arquivo/2024/Pasta Velha/f.bin").exists()


def test_move_refuses_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    r = MovePath().run({"src": "a.txt", "dst": "b.txt"}, _ctx(tmp_path))
    assert not r.ok
    assert (tmp_path / "b.txt").read_text() == "B"      # intocado


def test_move_missing_src_clean_error(tmp_path):
    r = MovePath().run({"src": "nada.txt", "dst": "x.txt"}, _ctx(tmp_path))
    assert not r.ok and "não existe" in r.output


def test_move_blocks_sensitive(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1")
    r = MovePath().run({"src": ".env", "dst": "fora.txt"}, _ctx(tmp_path))
    assert not r.ok


def test_move_respects_jail_on_dst(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    r = MovePath().run({"src": "a.txt", "dst": "../fora.txt"}, _ctx(tmp_path))
    assert not r.ok


def test_move_with_open_fs_reaches_outside(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outro = tmp_path / "Downloads"
    outro.mkdir()
    (outro / "doc.pdf").write_bytes(b"%PDF")
    ctx = _ctx(ws, open_fs=True)
    r = MovePath().run({"src": str(outro / "doc.pdf"), "dst": str(outro / "Docs/doc.pdf")}, ctx)
    assert r.ok, r.output
    assert (outro / "Docs/doc.pdf").exists()


# ── copy_path ───────────────────────────────────────────────────────────────

def test_copy_file(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    r = CopyPath().run({"src": "a.txt", "dst": "c/a.txt"}, _ctx(tmp_path))
    assert r.ok, r.output
    assert (tmp_path / "a.txt").exists() and (tmp_path / "c/a.txt").read_text() == "hi"


def test_copy_dir(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d/f.txt").write_text("x")
    r = CopyPath().run({"src": "d", "dst": "d2"}, _ctx(tmp_path))
    assert r.ok and (tmp_path / "d2/f.txt").exists()


# ── delete_path (lixeira reversível, nunca rm) ─────────────────────────────

def test_delete_moves_to_trash(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / ".okami"))
    (tmp_path / "velho.txt").write_text("bye")
    r = DeletePath().run({"path": "velho.txt"}, _ctx(tmp_path))
    assert r.ok, r.output
    assert not (tmp_path / "velho.txt").exists()
    trash = list((tmp_path / ".okami" / "trash").rglob("velho.txt"))
    assert trash and trash[0].read_text() == "bye"      # reversível


def test_delete_blocks_sensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / ".okami"))
    (tmp_path / ".env").write_text("SECRET=1")
    assert not DeletePath().run({"path": ".env"}, _ctx(tmp_path)).ok
    assert (tmp_path / ".env").exists()


# ── registro + policy de superfície ─────────────────────────────────────────

def test_tools_registered():
    reg = default_registry()
    for name in ("make_dir", "move_path", "copy_path", "delete_path"):
        assert name in reg, name


def test_allowed_on_telegram():
    from okami.core.tool_policy import denied
    for name in ("make_dir", "move_path", "copy_path", "delete_path"):
        assert not denied("telegram", name), name      # mesmo nível do write_file (sensitive)
