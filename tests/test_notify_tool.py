"""Testes da tool `notify` (item 3 da pesquisa #7).

A tool entrega uma mensagem ao DONO AGORA, fora do turno normal (avisar que
terminou, que precisa de aprovação, ou disparar um alerta). O canal de saída é o
hook `ctx.notify` (Callable[[str], bool] | None) — quando ausente (CLI/lib sem
dono), a tool falha em paz (fail-open), sem levantar exceção.
"""

from __future__ import annotations

from pathlib import Path

from okami.core.tools.base import ToolContext, ToolResult
from okami.core.tools.notify import Notify


def _ctx(tmp_path: Path, **kw) -> ToolContext:
    return ToolContext(workspace=tmp_path, **kw)


def test_notify_entrega_via_hook_e_retorna_ok(tmp_path):
    """ctx.notify setado → invocado COM a mensagem; ok True; efeito observável."""
    capturado: list[str] = []

    def _hook(msg: str) -> bool:
        capturado.append(msg)
        return True

    tool = Notify()
    res = tool.run({"message": "terminei o relatório"}, _ctx(tmp_path, notify=_hook))

    assert isinstance(res, ToolResult)
    assert res.ok is True
    assert res.effect is True
    assert capturado == ["terminei o relatório"]


def test_notify_sem_canal_falha_sem_levantar(tmp_path):
    """ctx.notify=None (CLI/lib sem dono) → ToolResult ok=False, SEM exceção."""
    tool = Notify()
    res = tool.run({"message": "oi"}, _ctx(tmp_path, notify=None))

    assert res.ok is False
    assert res.effect is False
    assert "indisponível" in res.output.lower()


def test_notify_message_vazio_falha(tmp_path):
    """message vazio (ou só espaços) → falha de validação, sem chamar o hook."""
    chamou: list[str] = []
    tool = Notify()
    res = tool.run({"message": "   "}, _ctx(tmp_path, notify=lambda m: chamou.append(m) or True))

    assert res.ok is False
    assert res.effect is False
    assert chamou == []  # hook NÃO foi chamado


def test_notify_message_ausente_falha(tmp_path):
    """sem a chave message → mesma falha de validação."""
    tool = Notify()
    res = tool.run({}, _ctx(tmp_path, notify=lambda m: True))
    assert res.ok is False
    assert res.effect is False


def test_notify_hook_retorna_false_propaga_falha(tmp_path):
    """hook entregou False (canal recusou) → ok False, output de falha, NÃO terminal."""
    tool = Notify()
    res = tool.run({"message": "alerta"}, _ctx(tmp_path, notify=lambda m: False))
    assert res.ok is False
    assert res.effect is False


def test_notify_message_strip(tmp_path):
    """a mensagem entregue ao hook vem SEM espaços nas pontas."""
    capturado: list[str] = []
    tool = Notify()
    tool.run({"message": "  precisa de aprovação  "},
             _ctx(tmp_path, notify=lambda m: capturado.append(m) or True))
    assert capturado == ["precisa de aprovação"]


def test_notify_metadados():
    """name/required/terminal conforme o contrato do item 3."""
    tool = Notify()
    assert tool.name == "notify"
    assert tool.required == ("message",)
    assert tool.terminal is False
    assert "message" in tool.args_schema
