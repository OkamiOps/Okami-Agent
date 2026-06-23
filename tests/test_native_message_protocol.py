"""Paridade Hermes no rail NATIVO: o resultado de uma tool_call volta como role=tool casando o id,
logo APÓS a mensagem assistant que echoou a tool_call (protocolo de function-calling, não user genérico).
Echo ATÔMICO: rejeição (nome inválido/etc) NÃO deixa tool_call órfã (que quebraria a próxima chamada)."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import Completion


def _assistant_with_tool_calls(messages):
    return [(i, m) for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")]


def test_native_dispatch_produces_valid_assistant_then_tool(tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo do arquivo", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "c1", "name": "read_file", "arguments": '{"path":"a.txt"}'}])
        return Completion(text="", tool_calls=[
            {"id": "c2", "name": "task_complete", "arguments": '{"summary":"li o arquivo"}'}])

    h = Harness(gen, Task(goal="leia a.txt"), tmp_path)
    h.run()
    asst = _assistant_with_tool_calls(h.messages)
    assert asst, "deveria haver assistant com tool_calls echoada"
    i, m = asst[0]
    assert m["tool_calls"][0]["id"] == "c1"                       # echoou a tool_call read_file
    assert h.messages[i + 1]["role"] == "tool"                   # resultado vem como role=tool…
    assert h.messages[i + 1]["tool_call_id"] == "c1"             # …casando o id (sequência válida)


def test_native_invalid_tool_leaves_no_orphan(tmp_path):
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "cX", "name": "zzzqqqnaoexiste", "arguments": "{}"}])   # nome inválido → rejeitado
        return Completion(text="", tool_calls=[
            {"id": "c2", "name": "task_complete", "arguments": '{"summary":"fim"}'}])

    h = Harness(gen, Task(goal="x"), tmp_path)
    h.run()
    # NENHUMA assistant com tool_calls pode ficar sem um role=tool logo após (órfã quebraria a API)
    for i, m in enumerate(h.messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            nxt = h.messages[i + 1] if i + 1 < len(h.messages) else {}
            assert nxt.get("role") == "tool", f"tool_call órfã na msg {i}"


def test_native_invalid_tool_gets_tool_role_error(tmp_path):
    # paridade Hermes: nome inválido vira ERRO role=tool (auto-correção nativa), não scold de user "emita json"
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "cBad", "name": "zzzqqqnaoexiste", "arguments": "{}"}])
        return Completion(text="", tool_calls=[
            {"id": "c2", "name": "task_complete", "arguments": '{"summary":"ok"}'}])

    h = Harness(gen, Task(goal="x"), tmp_path)
    h.run()
    errs = [m for m in h.messages if m.get("role") == "tool" and m.get("tool_call_id") == "cBad"]
    assert errs and "inválida" in errs[0]["content"]            # erro como role=tool, casando o id
    i = next(j for j, m in enumerate(h.messages)
             if m.get("role") == "assistant" and m.get("tool_calls", [{}])[0].get("id") == "cBad")
    assert h.messages[i + 1]["role"] == "tool"                  # echoada + resposta → sem órfã


def test_native_multiple_reads_run_in_one_turn(tmp_path):
    (tmp_path / "a.txt").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.txt").write_text("BBB", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "c1", "name": "read_file", "arguments": '{"path":"a.txt"}'},
                {"id": "c2", "name": "read_file", "arguments": '{"path":"b.txt"}'}])
        return Completion(text="", tool_calls=[
            {"id": "c3", "name": "task_complete", "arguments": '{"summary":"li os dois"}'}])

    h = Harness(gen, Task(goal="leia a e b"), tmp_path)
    h.run()
    assert calls["n"] == 2                                       # 2 leituras rodaram no MESMO turno (1 geração)
    asst = _assistant_with_tool_calls(h.messages)
    assert asst and asst[0][1]["tool_calls"][0]["id"] == "c1"   # 1ª echoada como tool_call
    assert h.messages[asst[0][0] + 1]["role"] == "tool"         # sequência válida
    blob = " ".join(str(m.get("content")) for m in h.messages)
    assert "AAA" in blob and "BBB" in blob                      # AMBOS os arquivos foram lidos


def test_native_multiple_writes_run_serially_in_one_turn(tmp_path):
    # paridade Hermes: várias MUTAÇÕES no mesmo turno (serial, gated), não 1/turno
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "w1", "name": "write_file", "arguments": '{"path":"x.txt","content":"X"}'},
                {"id": "w2", "name": "write_file", "arguments": '{"path":"y.txt","content":"Y"}'}])
        return Completion(text="", tool_calls=[
            {"id": "d", "name": "task_complete", "arguments": '{"summary":"escrevi os dois"}'}])

    h = Harness(gen, Task(goal="crie x e y"), tmp_path)
    h.run()
    assert calls["n"] == 2                                       # 2 escritas no MESMO turno (1 geração)
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "X"
    assert (tmp_path / "y.txt").read_text(encoding="utf-8") == "Y"
    asst = _assistant_with_tool_calls(h.messages)
    assert asst and asst[0][1]["tool_calls"][0]["id"] == "w1"   # 1ª declarada, sequência válida
    assert h.messages[asst[0][0] + 1]["role"] == "tool"


def test_json_rail_still_uses_user_observation(tmp_path):
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return '```json\n{"tool":"read_file","args":{"path":"b.txt"}}\n```'
        return '```json\n{"tool":"task_complete","args":{"summary":"ok"}}\n```'

    h = Harness(gen, Task(goal="leia b.txt"), tmp_path)
    h.run()
    assert not _assistant_with_tool_calls(h.messages)            # rail JSON: nada de tool_calls/role=tool
    assert any(m.get("role") == "user" and "OBSERVA" in (m.get("content") or "") for m in h.messages)
