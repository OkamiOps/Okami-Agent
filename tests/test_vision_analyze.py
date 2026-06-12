"""vision_analyze (pesquisa #6 item 4, paridade Hermes vision_tools) — dá visão a um modelo de texto
roteando a imagem por um modelo AUXILIAR multimodal (OCR, descrição de screenshot, etc.)."""
from __future__ import annotations

from okami.core.tools import ToolContext
from okami.core.tools.vision import VisionAnalyze
from okami.llm import vision


def _png(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fakeimage" * 4)
    return p


def test_build_messages_has_image_and_prompt(tmp_path):
    msgs = vision.build_vision_messages("o que tem aqui?", "data:image/png;base64,AAAA")
    user = msgs[-1]
    assert isinstance(user["content"], list)
    assert any(b.get("type") == "text" and "o que tem" in b.get("text", "") for b in user["content"])
    assert any(b.get("type") == "image_url" for b in user["content"])


def test_analyze_image_calls_aux(tmp_path):
    p = _png(tmp_path)
    seen = {}

    def fake(cfg, task, msgs, **kw):
        seen["task"] = task
        seen["has_image"] = any(b.get("type") == "image_url" for b in msgs[-1]["content"])
        return "uma tela de login"
    out = vision.analyze_image("CFG", str(p), "descreva", complete=fake)
    assert out == "uma tela de login"
    assert seen["task"] == "vision" and seen["has_image"]


def test_analyze_missing_file(tmp_path):
    out = vision.analyze_image("CFG", str(tmp_path / "nope.png"), "x", complete=lambda *a, **k: "y")
    assert "não" in out.lower() and ("exist" in out.lower() or "encontr" in out.lower())


# ------------------------------------------------------------------ tool
def test_tool_analyzes(tmp_path, monkeypatch):
    _png(tmp_path)
    monkeypatch.setattr(vision, "analyze_image", lambda cfg, path, prompt, **kw: "descrição da imagem")
    ctx = ToolContext(workspace=tmp_path, cfg=object())
    res = VisionAnalyze().run({"path": "shot.png", "prompt": "o que é isso?"}, ctx)
    assert res.ok and "descrição da imagem" in res.output


def test_tool_requires_path(tmp_path):
    ctx = ToolContext(workspace=tmp_path, cfg=object())
    res = VisionAnalyze().run({"prompt": "x"}, ctx)
    assert not res.ok


def test_tool_no_cfg(tmp_path):
    _png(tmp_path)
    res = VisionAnalyze().run({"path": "shot.png", "prompt": "x"}, ToolContext(workspace=tmp_path))
    assert not res.ok and ("auxiliar" in res.output.lower() or "config" in res.output.lower())


def test_registered():
    from okami.core.tools import default_registry
    assert "vision_analyze" in default_registry()
