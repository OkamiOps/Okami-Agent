"""compaction.compact(pending_todos=…) — reinjeção de checklist pós-compactação (pesquisa #7 item 9).

Quando o histórico é compactado, os itens em aberto (pending/in_progress) entram na nota do snapshot
pra o modelo CONTINUAR de onde parou. Itens completed NÃO entram. O framing anti-sequestro e a
alternância user/assistant ficam preservados."""

from __future__ import annotations

from okami.core.tools.todo import render_pending
from okami.memory import compaction


def _long_history(n=12):
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(n):
        role = "assistant" if i % 2 == 0 else "user"
        msgs.append({"role": role, "content": f"msg {i} " + "x" * 50})
    return msgs


def test_pending_todos_block_appended_to_snapshot():
    todos = [
        {"id": "1", "content": "ler o módulo X", "status": "completed"},
        {"id": "2", "content": "implementar a função Y", "status": "in_progress"},
        {"id": "3", "content": "escrever os testes", "status": "pending"},
    ]
    block = render_pending(todos)
    out, _ = compaction.compact(_long_history(), None, pending_todos=block)
    note = next(m["content"] for m in out if "SNAPSHOT" in (m.get("content") or ""))
    assert "implementar a função Y" in note          # in_progress reinjetado
    assert "escrever os testes" in note              # pending reinjetado
    assert "ler o módulo X" not in note              # completed NÃO reinjetado


def test_no_pending_todos_leaves_note_unchanged():
    out, _ = compaction.compact(_long_history(), None, pending_todos="")
    note = next(m["content"] for m in out if "SNAPSHOT" in (m.get("content") or ""))
    assert "CHECKLIST OPERACIONAL" not in note


def test_anti_hijack_framing_preserved_with_todos():
    block = render_pending([{"id": "1", "content": "tarefa pendente", "status": "pending"}])
    out, _ = compaction.compact(_long_history(), None, pending_todos=block)
    note = next(m["content"] for m in out if "SNAPSHOT" in (m.get("content") or ""))
    # o framing anti-sequestro continua de pé (a última msg do usuário VENCE)
    assert "a última mensagem do usuário" in note.lower() or "última mensagem do usuário" in note.lower()
    assert "FIM DO SNAPSHOT" in note
    # e o bloco de TODOs vem DEPOIS do framing anti-sequestro
    assert note.index("FIM DO SNAPSHOT") < note.index("tarefa pendente")


def test_user_alternation_preserved():
    """Se tail[0] for 'user', a nota+todos funde nela (sem duas 'user' seguidas)."""
    msgs = _long_history(12)
    # garante que o 1º do tail (keep_tail=6) seja 'user'
    block = render_pending([{"id": "1", "content": "tarefa pendente", "status": "pending"}])
    out, _ = compaction.compact(msgs, None, keep_tail=6, pending_todos=block)
    roles = [m["role"] for m in out]
    for a, b in zip(roles, roles[1:]):
        assert not (a == "user" and b == "user"), "duas 'user' seguidas quebram a alternância"


def test_pending_todos_default_is_backward_compatible():
    """Sem pending_todos (default ""), o comportamento antigo é idêntico."""
    out_old, _ = compaction.compact(_long_history(), None)
    out_new, _ = compaction.compact(_long_history(), None, pending_todos="")
    notes_old = [m["content"] for m in out_old if "SNAPSHOT" in (m.get("content") or "")]
    notes_new = [m["content"] for m in out_new if "SNAPSHOT" in (m.get("content") or "")]
    assert notes_old == notes_new
