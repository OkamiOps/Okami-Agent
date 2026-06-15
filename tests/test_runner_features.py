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


def test_failover_skips_experimental_provider(monkeypatch):
    # provider experimental NUNCA entra no failover automático (opt-in só explícito) → vai direto p/ 'c'.
    import okami.llm.providers as prov
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["x", "c"]},
        "x": {"model": "mx", "experimental": True},
        "c": {"model": "mc"}}})
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(pc.name)
        if pc.name == "a":
            raise RuntimeError("a caiu")
        return "ok do c"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    out = prov.complete_messages(cfg, [{"role": "user", "content": "oi"}])
    assert out == "ok do c"
    assert "x" not in calls and calls == ["a", "c"]   # pulou o experimental, caiu no próximo real


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


def test_spawn_parallel_tasks_fan_out():
    # #9 Tier 1: `tasks` roda N subagentes em PARALELO (fan-out) e junta os resultados rotulados.
    seen = []
    ctx = ToolContext(workspace=Path("."),
                      spawn=lambda goal, agent, model: (seen.append(goal), f"feito: {goal}")[1])
    r = Spawn().run({"tasks": [{"goal": "pesquisa A"}, {"goal": "pesquisa B"}, {"goal": "refatora C"}]}, ctx)
    assert r.ok
    assert "feito: pesquisa A" in r.output and "feito: pesquisa B" in r.output and "feito: refatora C" in r.output
    assert set(seen) == {"pesquisa A", "pesquisa B", "refatora C"}


def test_spawn_parallel_one_failure_does_not_sink_others():
    def _sp(goal, agent, model):
        if "ruim" in goal:
            raise RuntimeError("boom")
        return f"ok: {goal}"
    ctx = ToolContext(workspace=Path("."), spawn=_sp)
    r = Spawn().run({"tasks": [{"goal": "bom"}, {"goal": "ruim"}]}, ctx)
    assert r.ok and "ok: bom" in r.output and "falhou" in r.output    # o que falhou não derruba o resto


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
