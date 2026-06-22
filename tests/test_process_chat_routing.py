"""Item 2 da revisão de harness: a notificação de conclusão de processo deve ir pro chat que INICIOU o
processo (chat_id no meta → na nota de drain), não pro _last_chat global (que roteava errado quando outro
chat mandava msg antes de concluir)."""
from __future__ import annotations


def test_process_notification_carries_chat_id(tmp_path):
    from okami.core.processes import ProcessManager
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo oi", notify=True, chat_id="555")
    assert meta.get("chat_id") == "555"
    pm.wait(meta["id"], timeout=5)
    done = [n for n in pm.drain_notifications() if n.get("kind") == "complete"]
    assert done and done[0].get("chat_id") == "555"      # a nota carrega o chat de origem


def test_process_chat_id_defaults_empty(tmp_path):
    from okami.core.processes import ProcessManager
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo oi", notify=True)              # sem chat_id → "" (caller cai no fallback)
    assert meta.get("chat_id") == ""
