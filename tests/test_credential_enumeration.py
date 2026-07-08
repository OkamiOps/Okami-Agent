"""Incidente 2026-07-08: find_files/list_dir/search_files ENUMERAVAM credencial (só read_file barrava o
conteúdo). Em yolo o agente achava o caminho e partia p/ burlar. Agora credencial some da enumeração."""
import tempfile, shutil
from pathlib import Path
from okami.core.tools.files import FindFiles, ListDir
from okami.core.tools.search import SearchFiles


class _Ctx:
    def __init__(self, ws):
        self.workspace = ws; self.open_fs = False; self.read_files = set(); self.remote = None
        class _S: mode = "yolo"
        self.sandbox = _S()


def _mk():
    ws = Path(tempfile.mkdtemp())
    (ws / "client_secret_123.json").write_text('{"client_secret":"SEC"}')
    (ws / "credentials.json").write_text('{"token":"SEC"}')
    (ws / "app.py").write_text("x=1  # SEC marker\n")
    return ws


def test_find_files_nao_enumera_credencial_nem_em_yolo():
    ws = _mk(); c = _Ctx(ws)
    try:
        assert "client" not in FindFiles().run({"query": "client"}, c).output.lower() or "nada casou" in FindFiles().run({"query": "client"}, c).output
        assert "nada casou" in FindFiles().run({"query": "credential"}, c).output
    finally:
        shutil.rmtree(ws)


def test_list_dir_esconde_credencial_mostra_normal():
    ws = _mk(); c = _Ctx(ws)
    try:
        out = ListDir().run({"path": "."}, c).output
        assert "app.py" in out
        assert "client_secret" not in out and "credentials.json" not in out
    finally:
        shutil.rmtree(ws)


def test_search_files_nao_vaza_conteudo_de_credencial():
    ws = _mk(); c = _Ctx(ws)
    try:
        out = SearchFiles().run({"query": "SEC", "mode": "content"}, c).output
        assert "client_secret_123.json" not in out and "credentials.json" not in out
        assert "app.py" in out                     # arquivo normal ainda é buscável
    finally:
        shutil.rmtree(ws)
