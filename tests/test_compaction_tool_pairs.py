"""Paridade Hermes (#1 do sweep): compactação corta o MEIO e pode deixar par tool_call/tool_result órfão →
hard-400 no rail NATIVO (o caminho do minimax do dono). Repara: tira resultado role=tool sem a assistant
que o declarou, e põe stub p/ tool_call sem resultado. Sequência sempre válida pro provider."""
from __future__ import annotations

from okami.memory.compaction import _repair_tool_pairs, compact


def _call(cid):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": cid, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}


def test_repair_drops_orphan_tool_result():
    out = _repair_tool_pairs([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "snapshot"},
        {"role": "tool", "tool_call_id": "gone", "content": "resultado órfão"},  # assistant foi dropada
        {"role": "user", "content": "u"}])
    assert not any(m.get("role") == "tool" for m in out)        # órfã removida


def test_repair_stubs_unanswered_tool_call():
    out = _repair_tool_pairs([_call("c1"), {"role": "user", "content": "próximo"}])
    tools = [m for m in out if m.get("role") == "tool"]
    assert len(tools) == 1 and tools[0]["tool_call_id"] == "c1"  # stub criado
    ai = next(i for i, m in enumerate(out) if m.get("role") == "assistant")
    assert out[ai + 1].get("role") == "tool"                     # logo APÓS a assistant (sequência válida)


def test_repair_keeps_valid_pairs_untouched():
    msgs = [_call("c1"), {"role": "tool", "tool_call_id": "c1", "content": "ok"}]
    assert _repair_tool_pairs(msgs) == msgs


def test_compact_repairs_orphan_in_tail():
    msgs = [{"role": "system", "content": "s"}]
    for i in range(8):
        msgs += [{"role": "user", "content": f"u{i}"}, _call(f"c{i}"),
                 {"role": "tool", "tool_call_id": f"c{i}", "content": f"res{i}"}]
    out, _ = compact(msgs, None, keep_tail=1)                    # tail = [último tool] → órfão
    declared = set()
    for m in out:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                declared.add(tc["id"])
        if m.get("role") == "tool":
            assert m["tool_call_id"] in declared, "tool órfã sobreviveu à compactação"


def test_compaction_keeps_complete_native_group_intact():
    group = [
        _call("c1"),
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    out, _ = compact([{"role": "system", "content": "s"}, {"role": "user", "content": "old"}, *group],
                     None, keep_tail=1)
    assert out[-2:] == group
