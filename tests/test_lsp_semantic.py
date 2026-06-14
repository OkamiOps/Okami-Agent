"""LSP semântico (pesquisa #7 item 16) — diagnostics-on-write DELTA via pyright.

Onde o lint stdlib (item 6) pega só erro de SINTAXE, o LSP pega erro SEMÂNTICO: nome
indefinido, import quebrado, tipo errado. Mesmo contrato "só NOVO" do `lint_delta`: editar
arquivo já com erro não nagueia. Fail-open total — sem .git, sem pyright, sem .py → "".
Nunca levanta. Cliente JSON-RPC mínimo sobre stdio (subprocess), one-shot por arquivo.
"""
from __future__ import annotations

import json
import shutil

import pytest

from okami.core.lsp import pyright_client
from okami.core.lsp.diagnostics import lsp_delta


# ------------------------------------------------------------------ fail-open (sem dep)
def test_no_git_workspace_returns_empty(tmp_path):
    # sem pasta .git → não é projeto → "" (e nem tenta pyright)
    (tmp_path / "a.py").write_text("undefined_name\n")
    assert lsp_delta(tmp_path, "a.py", "", "undefined_name\n") == ""


def test_pyright_absent_returns_empty(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()                          # é projeto…
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)  # …mas sem binário
    assert lsp_delta(tmp_path, "a.py", "", "undefined_name\n") == ""


def test_non_python_file_returns_empty(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")
    # extensão não-.py → "" sem nem rodar pyright
    assert lsp_delta(tmp_path, "notas.md", "", "qualquer coisa") == ""


def test_pyright_binary_detection(monkeypatch):
    # detecta pyright-langserver OU basedpyright-langserver
    seen = {}

    def fake_which(name, *a, **k):
        seen[name] = True
        return "/opt/bin/" + name if name == "basedpyright-langserver" else None

    monkeypatch.setattr(shutil, "which", fake_which)
    found = pyright_client.find_binary()
    assert found == "/opt/bin/basedpyright-langserver"
    assert "pyright-langserver" in seen   # tentou o canônico primeiro


def test_pyright_binary_none_when_absent(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    assert pyright_client.find_binary() is None


# ------------------------------------------------------------------ parsing JSON-RPC (subprocess MOCKADO)
def _lsp_frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _canned_stdout(diagnostics: list[dict], uri: str = "file:///proj/a.py") -> bytes:
    """Stream de respostas que um servidor LSP enviaria: resposta do initialize + 1 publishDiagnostics."""
    init_resp = _lsp_frame({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}})
    diag_note = _lsp_frame({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                            "params": {"uri": uri, "diagnostics": diagnostics}})
    return init_resp + diag_note


class _FakePopen:
    """subprocess.Popen falso: devolve frames LSP enlatados no stdout; engole o que escrevem no stdin."""

    def __init__(self, canned: bytes):
        import io
        self.stdout = io.BytesIO(canned)
        self.stdin = io.BytesIO()
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return None

    def kill(self):
        self.returncode = -9

    def terminate(self):
        self.returncode = -15

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_parses_publish_diagnostics(monkeypatch, tmp_path):
    from pathlib import Path
    diags = [{"message": "\"foo\" is not defined", "severity": 1,
              "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}]
    # o URI do publishDiagnostics precisa bater com o que o cliente abre (file:// do arquivo real)
    uri = (Path(tmp_path) / "a.py").resolve().as_uri()
    canned = _canned_stdout(diags, uri=uri)
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")
    monkeypatch.setattr(pyright_client.subprocess, "Popen", lambda *a, **k: _FakePopen(canned))

    out = pyright_client.diagnose(tmp_path, "a.py", "foo\n")
    assert isinstance(out, list) and len(out) == 1
    assert "not defined" in out[0]["message"]


def test_client_returns_empty_when_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    assert pyright_client.diagnose(tmp_path, "a.py", "foo\n") == []


def test_client_never_raises_on_broken_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")

    def boom(*a, **k):
        raise OSError("não foi possível iniciar o servidor")

    monkeypatch.setattr(pyright_client.subprocess, "Popen", boom)
    assert pyright_client.diagnose(tmp_path, "a.py", "foo\n") == []   # engole o erro → []


# ------------------------------------------------------------------ delta keyed por (msg, símbolo), NÃO por linha
def test_delta_keys_by_symbol_not_line(monkeypatch, tmp_path):
    """O MESMO erro semântico que apenas DESLOCOU de linha não é NOVO (chave = msg+símbolo)."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")

    calls = {"n": 0}

    def fake_diagnose(workspace, rel, text):
        calls["n"] += 1
        # erro idêntico nos dois (before/after), só a linha muda → NÃO é novo
        line = 0 if calls["n"] == 1 else 5
        return [{"message": "\"foo\" is not defined", "severity": 1,
                 "range": {"start": {"line": line, "character": 0}}}]

    monkeypatch.setattr(pyright_client, "diagnose", fake_diagnose)
    before = "foo\n"
    after = "\n\n\n\n\nfoo\n"                  # mesmo erro, 5 linhas abaixo
    assert lsp_delta(tmp_path, "a.py", before, after) == ""   # deslocou de linha, não nagueia


def test_delta_flags_genuinely_new_error(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")

    def fake_diagnose(workspace, rel, text):
        if "bar" in text:                      # o 'after' introduziu bar
            return [{"message": "\"bar\" is not defined", "severity": 1,
                     "range": {"start": {"line": 0, "character": 0}}}]
        return []                              # before estava limpo

    monkeypatch.setattr(pyright_client, "diagnose", fake_diagnose)
    msg = lsp_delta(tmp_path, "a.py", "x = 1\n", "bar\n")
    assert msg and "bar" in msg


def test_delta_does_not_nag_preexisting(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")

    def fake_diagnose(workspace, rel, text):   # MESMO erro nos dois lados → preexistente
        return [{"message": "\"old\" is not defined", "severity": 1,
                 "range": {"start": {"line": 0, "character": 0}}}]

    monkeypatch.setattr(pyright_client, "diagnose", fake_diagnose)
    assert lsp_delta(tmp_path, "a.py", "old\n", "old\ny = 2\n") == ""


def test_delta_never_raises(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "/usr/bin/pyright-langserver")

    def boom(*a, **k):
        raise RuntimeError("pyright explodiu")

    monkeypatch.setattr(pyright_client, "diagnose", boom)
    assert lsp_delta(tmp_path, "a.py", "x\n", "y\n") == ""   # engole → ""


# ------------------------------------------------------------------ hook fino em code_lint (puro-stdlib no topo)
def test_code_lint_exposes_thin_hook():
    import okami.core.code_lint as cl
    assert hasattr(cl, "semantic_delta")        # hook fino
    # code_lint NÃO importa pyright no topo (mantém puro-stdlib): nada de pyright no módulo carregado
    src = open(cl.__file__, encoding="utf-8").read()
    head = src.split("def ")[0]                 # tudo antes da 1ª função = imports de topo
    assert "pyright" not in head.lower()
    assert "from okami.core.lsp" not in head


def test_code_lint_semantic_delta_fail_open(tmp_path):
    # sem .git/sem pyright → "" (mesma garantia do lsp_delta)
    import okami.core.code_lint as cl
    assert cl.semantic_delta(tmp_path, "a.py", "", "undefined\n") == ""


# ------------------------------------------------------------------ servidor REAL (só se pyright instalado)
@pytest.mark.skipif(shutil.which("pyright-langserver") is None
                    and shutil.which("basedpyright-langserver") is None,
                    reason="pyright-langserver não instalado")
def test_real_undefined_name_flagged_as_new(tmp_path):
    (tmp_path / ".git").mkdir()
    before = "x = 1\n"
    after = "x = 1\nresultado = nome_que_nao_existe + 1\n"   # nome indefinido NOVO
    msg = lsp_delta(tmp_path, "modulo.py", before, after)
    assert msg != ""                            # erro semântico novo → avisa


@pytest.mark.skipif(shutil.which("pyright-langserver") is None
                    and shutil.which("basedpyright-langserver") is None,
                    reason="pyright-langserver não instalado")
def test_real_preexisting_error_not_nagged(tmp_path):
    (tmp_path / ".git").mkdir()
    before = "valor = ja_quebrado_antes\n"      # já tinha erro
    after = "valor = ja_quebrado_antes\noutra = 2\n"   # continua, mas o erro é o MESMO
    assert lsp_delta(tmp_path, "modulo.py", before, after) == ""   # não nagueia o preexistente
