"""Plugin built-in disk-cleanup (#20, port do Hermes) — rastreia arquivos EFÊMEROS que o agente escreve
(temp/scratch/*.tmp…) e os apaga no fim da tarefa. Dois hooks: before_tool (track, nunca veta) +
after_task (clean). Testado pelo CONTRATO real (scripts como subprocesso, estado em OKAMI_HOME).
SEGURANÇA: só apaga o que ele MESMO classificou como efêmero, re-verifica na hora de apagar, nunca
segue symlink, nunca apaga diretório."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRACK = REPO / "plugins" / "disk-cleanup" / "hooks" / "before_tool" / "track.py"
CLEAN = REPO / "plugins" / "disk-cleanup" / "hooks" / "after_task" / "clean.py"


def _env(home: Path) -> dict:
    e = {**os.environ, "OKAMI_HOME": str(home)}
    e.pop("OKAMI_DISKCLEAN_GLOBS", None)
    return e


def _track(payload: dict, *, cwd: Path, home: Path) -> int:
    e = {**_env(home), "OKAMI_HOOK_PAYLOAD": json.dumps(payload)}
    return subprocess.run([sys.executable, str(TRACK)], env=e, cwd=str(cwd),
                          capture_output=True, text=True, timeout=20).returncode


def _clean(*, cwd: Path, home: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CLEAN)], env={**_env(home), "OKAMI_HOOK_PAYLOAD": "{}"},
                       cwd=str(cwd), capture_output=True, text=True, timeout=20)
    return r.returncode, (r.stdout + r.stderr)


def _state(home: Path) -> dict:
    f = home / "disk-cleanup" / "tracked.json"
    return json.loads(f.read_text()) if f.is_file() else {}


# ── track: efêmero é registrado; normal é ignorado ──
def test_track_records_ephemeral(tmp_path):
    home = tmp_path / "home"
    (tmp_path / "scratch.tmp").write_text("lixo")
    rc = _track({"tool": "write_file", "args": {"path": "scratch.tmp"}}, cwd=tmp_path, home=home)
    assert rc == 0
    tracked = [p for paths in _state(home).values() for p in paths]
    assert os.path.realpath(str(tmp_path / "scratch.tmp")) in tracked


def test_track_ignores_normal_source(tmp_path):
    home = tmp_path / "home"
    rc = _track({"tool": "write_file", "args": {"path": "main.py"}}, cwd=tmp_path, home=home)
    assert rc == 0
    tracked = [p for paths in _state(home).values() for p in paths]
    assert os.path.realpath(str(tmp_path / "main.py")) not in tracked


def test_track_never_vetoes_even_on_bad_payload(tmp_path):
    e = {**_env(tmp_path / "home"), "OKAMI_HOOK_PAYLOAD": "{quebrado"}
    rc = subprocess.run([sys.executable, str(TRACK)], env=e, cwd=str(tmp_path),
                        capture_output=True, text=True, timeout=20).returncode
    assert rc == 0                                          # before_tool nunca veta por causa do cleanup


def test_track_records_added_files_from_patch(tmp_path):
    home = tmp_path / "home"
    patch = "*** Begin Patch\n*** Add File: out.tmp\n+conteudo\n*** End Patch\n"
    (tmp_path / "out.tmp").write_text("conteudo")
    _track({"tool": "apply_patch", "args": {"patch": patch}}, cwd=tmp_path, home=home)
    tracked = [p for paths in _state(home).values() for p in paths]
    assert os.path.realpath(str(tmp_path / "out.tmp")) in tracked


# ── clean: apaga o efêmero presente, limpa o estado ──
def test_clean_removes_tracked_ephemeral(tmp_path):
    home = tmp_path / "home"
    f = tmp_path / "scratch.tmp"
    f.write_text("lixo")
    _track({"tool": "write_file", "args": {"path": "scratch.tmp"}}, cwd=tmp_path, home=home)
    rc, out = _clean(cwd=tmp_path, home=home)
    assert rc == 0 and not f.exists()                       # apagado
    assert "1" in out                                       # relata 1 removido
    assert not _state(home).get(str(tmp_path))              # estado do projeto zerado


def test_clean_skips_missing_file(tmp_path):
    home = tmp_path / "home"
    _track({"tool": "write_file", "args": {"path": "gone.tmp"}}, cwd=tmp_path, home=home)
    # arquivo nunca criado → clean não deve falhar
    rc, _ = _clean(cwd=tmp_path, home=home)
    assert rc == 0


def test_clean_refuses_symlink(tmp_path):
    home = tmp_path / "home"
    real = tmp_path / "precious.txt"
    real.write_text("NÃO APAGAR")
    link = tmp_path / "evil.tmp"
    link.symlink_to(real)
    # força o estado a apontar p/ o symlink (mesmo que o track também recusasse)
    sd = home / "disk-cleanup"
    sd.mkdir(parents=True)
    (sd / "tracked.json").write_text(json.dumps({str(tmp_path): [str(link)]}))
    rc, _ = _clean(cwd=tmp_path, home=home)
    assert rc == 0
    assert real.exists() and real.read_text() == "NÃO APAGAR"   # alvo do symlink intacto


def test_clean_only_touches_current_project(tmp_path):
    home = tmp_path / "home"
    other = tmp_path / "other_proj"
    other.mkdir()
    other_tmp = other / "x.tmp"
    other_tmp.write_text("de outro projeto")
    sd = home / "disk-cleanup"
    sd.mkdir(parents=True)
    (sd / "tracked.json").write_text(json.dumps({str(other): [str(other_tmp)]}))
    rc, _ = _clean(cwd=tmp_path, home=home)                 # cwd != other → não mexe
    assert rc == 0 and other_tmp.exists()
