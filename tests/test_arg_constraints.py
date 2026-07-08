"""FIX1/FIX2 da auditoria 2026-07: to_openai_schema() ganhou enum/default/minimum/maximum por arg
(antes só emitia {type, description} — #1 driver de tool-call ruim, o modelo "chutava" valor fora
do domínio). `arg_constraints` é o mecanismo de declaração (dict opcional em cada Tool subclass);
este arquivo testa a emissão genérica em base.py e a aplicação nas tools multi-modo que possuo
(search_files, spawn_jobs, spawn, todo_write)."""
from __future__ import annotations

from okami.core.tools.agentic import Spawn, SpawnJobs
from okami.core.tools.base import Tool, ToolResult
from okami.core.tools.search import SearchFiles
from okami.core.tools.todo import TodoWrite


class _Dummy(Tool):
    name = "dummy"
    description = "tool de teste"
    args_schema = {"mode": "modo de operação", "count": "quantidade", "flag": "liga/desliga"}
    arg_types = {"count": "integer", "flag": "boolean"}
    arg_constraints = {
        "mode": {"enum": ["a", "b", "c"], "default": "a"},
        "count": {"minimum": 0, "maximum": 10, "default": 1},
    }
    required = ()

    def run(self, args, ctx) -> ToolResult:  # pragma: no cover — só a forma do schema importa aqui
        return ToolResult(True, "ok")


# ---------- emissão genérica (base.py) ----------

def test_to_openai_schema_emite_enum_default_min_max():
    sch = _Dummy().to_openai_schema()
    props = sch["function"]["parameters"]["properties"]
    assert props["mode"]["enum"] == ["a", "b", "c"]
    assert props["mode"]["default"] == "a"
    assert props["count"]["minimum"] == 0
    assert props["count"]["maximum"] == 10
    assert props["count"]["default"] == 1
    # tipo continua vindo de arg_types, como antes
    assert props["count"]["type"] == "integer"
    assert props["flag"]["type"] == "boolean"


def test_arg_sem_constraint_nao_ganha_chaves_extras():
    sch = _Dummy().to_openai_schema()
    props = sch["function"]["parameters"]["properties"]
    assert set(props["flag"].keys()) == {"type", "description"}


def test_tool_sem_arg_constraints_continua_funcionando():
    """Tool que não declara arg_constraints (a maioria) não quebra — dict vazio por default."""
    class _Plain(Tool):
        name = "plain"
        description = "sem constraints"
        args_schema = {"x": "algo"}

        def run(self, args, ctx):  # pragma: no cover
            return ToolResult(True, "ok")

    sch = _Plain().to_openai_schema()
    assert sch["function"]["parameters"]["properties"]["x"] == {"type": "string", "description": "algo"}


# ---------- FIX2: tools multi-modo que eu possuo ----------

def test_search_files_schema_tem_enum_de_target_e_mode():
    sch = SearchFiles().to_openai_schema()
    props = sch["function"]["parameters"]["properties"]
    assert props["target"]["enum"] == ["content", "files"]
    assert props["mode"]["enum"] == ["content", "files", "count"]
    assert props["mode"]["default"] == "content"


def test_spawn_jobs_schema_tem_enum_de_action():
    sch = SpawnJobs().to_openai_schema()
    props = sch["function"]["parameters"]["properties"]
    assert props["action"]["enum"] == ["list", "status", "result", "await"]
    assert props["timeout"]["type"] == "integer"
    assert props["timeout"]["maximum"] == 300


def test_spawn_background_tem_tipo_boolean():
    """`background` não tinha arg_types → rail nativo mandava "false" (string) e bool("false") é
    True (bug, mesmo caso de replace_all em files.py). Verificado (não estava declarado)."""
    sch = Spawn().to_openai_schema()
    props = sch["function"]["parameters"]["properties"]
    assert props["background"]["type"] == "boolean"
    assert props["background"]["default"] is False


def test_todo_write_schema_status_cancelled_documentado_na_descricao():
    t = TodoWrite()
    assert "cancelled" in t.args_schema["todos"]
    sch = t.to_openai_schema()
    assert sch["function"]["parameters"]["required"] == []   # `todos` agora opcional
