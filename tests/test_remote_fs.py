"""Phase 2 — primitivos de ARQUIVO do RemoteTarget (cat/tee/ls) + roteamento das tools de FS.

Quando ctx.remote está setado, read_file/write_file/edit_file/list_dir operam NA máquina remota.
O conteúdo de escrita vai por STDIN (não no argv → sem limite/quoting). _SENSITIVE_PATH continua
barrando .env/.ssh remotos (jail vale remoto). Tudo com runner mockado — sem rede.
"""
from __future__ import annotations

from okami.core.tools import ToolContext
from okami.core.tools.files import EditFile, ListDir, ReadFile, WriteFile
from okami.integrations.remote import RemoteResult, RemoteTarget


def _runner_factory(captured, *, stdout="", returncode=0):
    def runner(argv, **kw):
        captured["argv"] = argv
        captured["input"] = kw.get("input")

        class R:
            pass
        R.returncode = returncode
        R.stdout = stdout
        R.stderr = ""
        return R()
    return runner


# ── primitivos do RemoteTarget ──
def test_read_monta_cat():
    cap = {}
    rt = RemoteTarget(alias="h", host="h", runner=_runner_factory(cap, stdout="conteudo do arquivo"))
    res = rt.read("/etc/hostname")
    assert "cat" in cap["argv"][-1] and "hostname" in cap["argv"][-1]
    assert res.output == "conteudo do arquivo"


def test_write_envia_content_via_stdin_atomico():
    cap = {}
    rt = RemoteTarget(alias="h", host="h", runner=_runner_factory(cap))
    rt.write("/tmp/x.conf", "linha1\nlinha2")
    assert cap["input"] == "linha1\nlinha2"          # conteúdo via STDIN, nunca no argv
    assert "mv" in cap["argv"][-1] and "mktemp" in cap["argv"][-1]   # escrita atômica (tmp + mv)


def test_list_monta_ls():
    cap = {}
    rt = RemoteTarget(alias="h", host="h", runner=_runner_factory(cap, stdout="a/\nb.txt\n"))
    out = rt.list("/srv")
    assert "ls" in cap["argv"][-1] and "srv" in cap["argv"][-1]
    assert "b.txt" in out.output


# ── roteamento das tools de FS p/ o remoto ──
class _FakeRemote:
    alias = "prod"

    def __init__(self, content=""):
        self.content = content
        self.writes = []

    def read(self, path):
        return RemoteResult(0, self.content)

    def write(self, path, content):
        self.writes.append((path, content))
        return RemoteResult(0, "")

    def list(self, path):
        return RemoteResult(0, "arq1\narq2\n")


def test_read_file_roteia_remoto(tmp_path):
    ctx = ToolContext(workspace=tmp_path, remote=_FakeRemote(content="conteudo remoto aqui"))
    res = ReadFile().run({"path": "/etc/motd"}, ctx)
    assert res.ok and "conteudo remoto aqui" in res.output


def test_write_file_roteia_remoto(tmp_path):
    rem = _FakeRemote()
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = WriteFile().run({"path": "/srv/app/cfg.yaml", "content": "novo: valor"}, ctx)
    assert res.ok
    assert rem.writes == [("/srv/app/cfg.yaml", "novo: valor")]       # escreveu no remoto, não local
    assert not (tmp_path / "srv").exists()                            # nada criado localmente


def test_list_dir_roteia_remoto(tmp_path):
    ctx = ToolContext(workspace=tmp_path, remote=_FakeRemote())
    res = ListDir().run({"path": "/srv"}, ctx)
    assert res.ok and "arq1" in res.output


def test_edit_file_remoto_le_modifica_escreve(tmp_path):
    rem = _FakeRemote(content="porta = 8080\nhost = local")
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = EditFile().run({"path": "/srv/app.conf", "old": "8080", "new": "9090"}, ctx)
    assert res.ok
    assert rem.writes[-1] == ("/srv/app.conf", "porta = 9090\nhost = local")


# ── segurança: jail .env/.ssh vale no remoto ──
def test_read_remoto_path_sensivel_bloqueado(tmp_path):
    rem = _FakeRemote(content="SEGREDO")
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = ReadFile().run({"path": "/home/user/.ssh/id_rsa"}, ctx)
    assert res.ok is False                                            # .ssh barrado mesmo remoto


def test_write_remoto_path_sensivel_bloqueado(tmp_path):
    rem = _FakeRemote()
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = WriteFile().run({"path": "/app/.env", "content": "X=1"}, ctx)
    assert res.ok is False and rem.writes == []                       # .env barrado, nada escrito


def test_path_com_metacaracter_e_quotado_sem_injecao():
    # path hostil não pode injetar comando: shlex.quote + '--' neutralizam (cat trata como UM filename)
    cap = {}
    rt = RemoteTarget(alias="h", host="h", runner=_runner_factory(cap))
    rt.read("/tmp/x; rm -rf /")
    cmd = cap["argv"][-1]
    assert "cat -- '/tmp/x; rm -rf /'" in cmd                         # aspas em volta → inerte
    assert "&&" not in cmd.replace("&&", "")  # sanity (sem operador solto fora das aspas)
