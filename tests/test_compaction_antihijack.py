"""Nota de compactação ANTI-SEQUESTRO (pesquisa #5 item 1, doutrina do Hermes context_compressor).

O resumo de compactação NÃO pode ler como instrução/TODO ativo: um snapshot que diz "continue
implementando X" sequestra o turno quando o usuário já disse "para". A nota precisa de:
- título de SNAPSHOT HISTÓRICO (referência, não ordem);
- a regra explícita: a última mensagem do usuário VENCE; "para"/"desfaz" encerra o trabalho do resumo;
- marcador de FIM (o modelo sabe onde o histórico acaba e a conversa atual começa).
"""
from __future__ import annotations

from okami.memory.compaction import compact


def _msgs(n: int = 12) -> list[dict]:
    out = [{"role": "system", "content": "sys"}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"msg {i} " + "x" * 60})
    return out


def test_note_frames_as_historical_snapshot_reference_only():
    msgs, _ = compact(_msgs(), None)
    note = msgs[1]["content"]
    assert "SNAPSHOT HISTÓRICO" in note            # título: não lê como TODO ativo
    assert "REFERÊNCIA" in note.upper()


def test_note_says_last_user_message_wins():
    msgs, _ = compact(_msgs(), None)
    note = msgs[1]["content"]
    assert "VENCE" in note                          # última mensagem do usuário VENCE
    assert "para" in note.lower() and "desfaz" in note.lower()


def test_note_has_end_marker():
    msgs, _ = compact(_msgs(), None)
    note = msgs[1]["content"]
    assert "[FIM DO SNAPSHOT" in note


def test_note_with_memory_backend_keeps_antihijack_frame():
    class Mem:
        def write(self, item):
            pass

    msgs, _ = compact(_msgs(), Mem())
    note = msgs[1]["content"]
    assert "SNAPSHOT HISTÓRICO" in note and "[FIM DO SNAPSHOT" in note
