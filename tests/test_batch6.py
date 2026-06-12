"""Testes do lote: credential pools, vision capability, auto-skill LLM, browser, ACP, imagegen."""

from __future__ import annotations

import io
import json

from okami.config import build_config


# ---------------------------------------------------------------- credential pools (§3.5)
def test_key_pool_dedup_and_order():
    pc = build_config({"default_provider": "p", "providers": {
        "p": {"model": "m", "api_keys": ["k1", "k2"], "api_key": "k2"}}}).provider("p")
    assert pc.key_pool() == ["k1", "k2"]                       # dedup (k2 repetido)


def test_credential_pool_rotates_then_failover(monkeypatch):
    import okami.llm.providers as prov
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "api_keys": ["k1", "k2"], "fallback": ["b"]},
        "b": {"model": "mb", "api_key": "kb"}}})
    used = []

    def fake_one(pc, messages, model, schema, overrides):
        if pc.name == "a":
            used.append(overrides.get("_api_key"))
            raise RuntimeError("429")                          # ambas as chaves de 'a' falham
        return "ok-b"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    assert prov.complete_messages(cfg, [{"role": "user", "content": "x"}],
                                  _sleep=lambda s: None) == "ok-b"   # sem backoff real no teste
    assert used == ["k1", "k2"]                                # rotacionou as 2 chaves antes do failover


# ---------------------------------------------------------------- vision capability (§6)
def test_vision_capability_default_false():
    pc = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}}).provider("p")
    assert pc.capability.vision is False


# ---------------------------------------------------------------- auto-skill LLM (§7)
def test_distill_skill_llm_falls_back_when_no_cfg():
    from okami.core import Step, Task, TaskState
    from okami import learning
    t = Task(goal="x")
    t.state = TaskState.COMPLETE
    t.steps = [Step(i, tl, {}, "", True) for i, tl in enumerate(["a", "b", "c", "d"])]
    assert learning.distill_skill_llm(None, t) is None         # sem cfg → None (LLM-ou-nada: NADA é gravado)


# ---------------------------------------------------------------- browser (§13)
def test_browser_strip_html():
    from okami.integrations.browser import _strip_html
    out = _strip_html("<html><style>x{}</style><body>Olá <b>mundo</b></body></html>")
    assert "Olá mundo" in out and "{}" not in out


# ---------------------------------------------------------------- ACP (§13)
def test_acp_initialize_and_prompt_roundtrip():
    from okami.integrations.acp import run_acp
    from okami.core import Task, TaskState

    def framed(msg):
        b = json.dumps(msg).encode()
        return f"Content-Length: {len(b)}\r\n\r\n".encode() + b

    inp = io.BytesIO(framed({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                     + framed({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {}})
                     + framed({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                               "params": {"sessionId": "sess-1",
                                          "prompt": [{"type": "text", "text": "oi"}]}}))
    out = io.BytesIO()

    def fake_run_task(cfg, ws, goal, **kw):   # ACP agora passa on_event/cancel (streaming + cancel)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, f"feito: {goal}"
        return t

    run_acp(None, ".", fake_run_task, stdin=inp, stdout=out)
    raw = out.getvalue().decode()
    assert "protocolVersion" in raw and "sess-1" in raw
    assert "feito: oi" in raw and "end_turn" in raw            # prompt → harness → resultado


# ---------------------------------------------------------------- image-gen 2 fluxos (§13)
def test_imagegen_two_flows(monkeypatch, tmp_path):
    import base64
    import okami.llm.imagegen as ig

    calls = {}
    png_b64 = base64.b64encode(b"\x89PNG").decode()

    class FakeResp:
        def __init__(self, body): self._b = body
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        calls["url"] = req.full_url
        calls["ctype"] = dict(req.header_items()).get("Content-type", "")
        return FakeResp(b'{"data":[{"b64_json":"%s"}]}' % png_b64.encode())

    monkeypatch.setattr(ig, "_token", lambda: "tok")
    monkeypatch.setattr(ig.urllib.request, "urlopen", fake_urlopen)

    # fluxo SEM referência → generations (JSON)
    ig.generate_image("um gato", str(tmp_path / "a.png"))
    assert calls["url"].endswith("/images/generations") and "json" in calls["ctype"]
    assert (tmp_path / "a.png").exists()

    # fluxo COM referência → edits (multipart)
    ref = tmp_path / "foto.png"
    ref.write_bytes(b"\x89PNG")
    ig.generate_image("vire um infográfico", str(tmp_path / "b.png"), references=[str(ref)])
    assert calls["url"].endswith("/images/edits") and "multipart/form-data" in calls["ctype"]
