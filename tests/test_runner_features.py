"""Testes de failover de provider (#2), subagente/spawn (#1) e @-referências (#3)."""

from __future__ import annotations

from pathlib import Path

from okami.config import build_config
from okami.core.tools import Spawn, ToolContext
from okami.integrations.references import expand_references


def test_provider_failover_to_backup(monkeypatch):
    import okami.llm.providers as prov

    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"]}, "b": {"model": "mb"}}})
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(pc.name)
        if pc.name == "a":
            raise RuntimeError("provider a caiu")
        return "resposta do backup"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    out = prov.complete_messages(cfg, [{"role": "user", "content": "oi"}])
    assert out == "resposta do backup" and calls == ["a", "b"]   # caiu em a → tentou b


def test_failover_raises_if_all_fail(monkeypatch):
    import pytest

    import okami.llm.providers as prov
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"]}, "b": {"model": "mb"}}})
    monkeypatch.setattr(prov, "_complete_one",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("tudo caiu")))
    with pytest.raises(RuntimeError):
        prov.complete_messages(cfg, [{"role": "user", "content": "oi"}])


def test_spawn_tool_delegates_to_subagent():
    ctx = ToolContext(workspace=Path("."), spawn=lambda goal, agent, model: f"sub[{agent}]:{goal}")
    r = Spawn().run({"goal": "fazer o frontend", "agent": "ui"}, ctx)
    assert r.ok and "sub[ui]:fazer o frontend" in r.output


def test_spawn_unavailable_when_no_spawn():
    r = Spawn().run({"goal": "x"}, ToolContext(workspace=Path(".")))
    assert not r.ok and "indisponível" in r.output


def test_expand_references_file_url_and_missing(tmp_path):
    (tmp_path / "notes.md").write_text("conteudo importante", encoding="utf-8")
    text, block = expand_references("considere @notes.md ao fazer", tmp_path)
    assert text == "considere @notes.md ao fazer"               # texto preservado
    assert "@notes.md" in block and "conteudo importante" in block
    _, empty = expand_references("@naoexiste.txt", tmp_path)
    assert empty == ""                                          # ref que não casa é ignorada


def test_expand_references_dir_listing(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    _, block = expand_references("@src", tmp_path)
    assert "a.py" in block


def test_references_do_not_escape_workspace(tmp_path):
    (tmp_path.parent / "secret.txt").write_text("SEGREDO", encoding="utf-8")
    _, block = expand_references("@../secret.txt", tmp_path)
    assert "SEGREDO" not in block                               # não vaza fora do workspace


def test_vision_user_message_includes_image_block(tmp_path):
    from okami.core.harness import _user_start

    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    content = _user_start([str(img)])
    assert isinstance(content, list) and any(b.get("type") == "image_url" for b in content)
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")   # local → data URL
    assert _user_start(["https://e/i.png"])[1]["image_url"]["url"] == "https://e/i.png"  # URL passa direto
    assert _user_start([]) == "Comece."                        # sem imagem → texto simples
