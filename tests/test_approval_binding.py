"""Approval binding (#1/#9): a aprovação carrega tool + args_hash (amarra à ação exata)."""

from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import Completion


def _J(tool, **args):
    import json
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


def test_approval_request_carries_tool_and_args_hash(tmp_path):
    seen = {}

    def approver(req):
        seen.clear()
        seen.update(req)
        return False                       # nega → não escreve (write_file em SOUL.md é sensível)

    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text=_J("write_file", path="SOUL.md", content="novo eu"))
        return Completion(text=_J("respond", message="ok, deixa pra lá"))

    Harness(gen, Task(goal="muda o SOUL"), tmp_path, approve=approver).run()
    assert seen.get("tool") == "write_file"
    assert len(seen.get("args_hash", "")) == 16            # sha256[:16] dos args exatos
    assert seen.get("args", {}).get("path") == "SOUL.md"


def test_args_hash_is_deterministic_and_args_sensitive(tmp_path):
    """O mesmo conjunto de args → mesmo hash; args diferentes → hash diferente (anti-replay)."""
    hashes = []

    def approver(req):
        hashes.append(req["args_hash"])
        return False

    def gen_for(path):
        def gen(messages, schema=None):
            return Completion(text=_J("write_file", path=path, content="x"))
        return gen

    Harness(gen_for("SOUL.md"), Task(goal="x"), tmp_path / "a", approve=approver).run()
    h_a1 = hashes[0]
    hashes.clear()
    Harness(gen_for("SOUL.md"), Task(goal="x"), tmp_path / "a2", approve=approver).run()
    assert hashes[0] == h_a1                                 # mesmos args → mesmo hash
    hashes.clear()
    Harness(gen_for("VOICE.md"), Task(goal="x"), tmp_path / "b", approve=approver).run()
    assert hashes[0] != h_a1                                 # args diferentes → hash diferente
