"""Testes de failover de provider (#2), subagente/spawn (#1) e @-referências (#3)."""

from __future__ import annotations

from pathlib import Path

from okami.config import build_config
from okami.core.tools import Spawn, ToolContext
from okami.integrations.references import expand_references


def test_provider_failover_to_backup(monkeypatch):
    import okami.llm.providers as prov

    # max_retries=1: teste é sobre FAILOVER (não sobre a fila de retry do FIX 3) — 1 tentativa em 'a' basta.
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"], "max_retries": 1}, "b": {"model": "mb"}}})
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
        "a": {"model": "ma", "fallback": ["x", "c"], "max_retries": 1},
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
        "a": {"model": "ma", "fallback": ["b"], "max_retries": 1},
        "b": {"model": "mb", "max_retries": 1}}})
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


def test_reference_credential_denylist_blocks_dotenv(tmp_path):
    # FIX 1 (segurança): @file:.env é recusado — vira placeholder, o segredo nunca entra no bloco.
    (tmp_path / ".env").write_text("API_KEY=super-secreto", encoding="utf-8")
    _, block = expand_references("dá uma olhada em @file:.env", tmp_path)
    assert "super-secreto" not in block
    assert "credencial bloqueada" in block


def test_reference_credential_denylist_blocks_ssh_key_outside_workspace(tmp_path):
    # ~/.ssh/id_rsa é barrado pelo deny-list ANTES do escape-check (mesmo fora do workspace).
    _, block = expand_references("@file:~/.ssh/id_rsa", tmp_path)
    assert "credencial bloqueada" in block


def test_reference_file_line_range(tmp_path):
    (tmp_path / "foo.py").write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")
    _, block = expand_references("veja @file:foo.py:2-4", tmp_path)
    assert "l2" in block and "l3" in block and "l4" in block
    assert "l1" not in block and "l5" not in block


def test_reference_diff_and_staged(tmp_path, monkeypatch):
    import okami.integrations.references as refs

    calls = []

    def fake_diff(cmd, cwd, capture_output, text, timeout):
        calls.append(cmd)
        class R:
            stdout = "diff-fake"
        return R()

    monkeypatch.setattr(refs.subprocess, "run", fake_diff)
    _, block = expand_references("@diff e @staged", tmp_path)
    assert "diff-fake" in block
    assert any("--cached" in c for c in calls)                 # @staged usou git diff --cached


def test_reference_git_log(tmp_path, monkeypatch):
    import okami.integrations.references as refs

    def fake_log(cmd, cwd, capture_output, text, timeout):
        class R:
            stdout = "abc123 commit 1\ndef456 commit 2\n"
        return R()

    monkeypatch.setattr(refs.subprocess, "run", fake_log)
    _, block = expand_references("@git:2", tmp_path)
    assert "commit 1" in block and "commit 2" in block


def test_reference_budget_guard_truncates_huge_folder(tmp_path):
    big = "x" * 9000
    (tmp_path / "big").mkdir()
    for i in range(6):
        (tmp_path / "big" / f"f{i}.txt").write_text(big, encoding="utf-8")
    _, block = expand_references("@folder:big", tmp_path)
    assert "TRUNCADO" in block
    assert len(block) < 6 * 9000                                 # não injetou tudo


def test_vision_user_message_includes_image_block(tmp_path):
    from okami.core.harness import _user_start

    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    content = _user_start([str(img)])
    assert isinstance(content, list) and any(b.get("type") == "image_url" for b in content)
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")   # local → data URL
    assert _user_start(["https://e/i.png"])[1]["image_url"]["url"] == "https://e/i.png"  # URL passa direto
    assert _user_start([]) == "Comece."                        # sem imagem → texto simples


# ---------------------------------------------------------------- restricted toolset for spawned children
def test_spawned_child_registry_strips_delegation_and_skill_authoring(tmp_path, monkeypatch):
    """Gap: um subagente spawnado herdava o toolset INTEIRO do pai (spawn/manage_skill/install_skill
    incluídos), bounded só pelo teto de profundidade. Um leaf subagent não deve poder spawnar de novo nem
    autorar/instalar skill — só quem recebeu a tarefa do dono decide isso (Hermes: delegate_tool.py strip
    do children). Verifica via runner.run_task ponta-a-ponta: um spy no Harness real captura o registry
    FINAL que cada nível (pai/filho) efetivamente recebe."""
    import okami.core as core_mod
    import okami.llm.providers as prov
    import okami.runner as runner_mod
    from okami.config import build_config
    from okami.core import TaskState
    from okami.llm.usage import Completion
    from okami.runner import run_task

    real_harness = core_mod.Harness
    harnesses = []

    def _capturing_harness(gen, task, ws, **kw):
        harnesses.append(kw)
        return real_harness(gen, task, ws, **kw)
    monkeypatch.setattr(runner_mod, "Harness", _capturing_harness)

    calls = {"n": 0}

    def _fake(cfg, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:               # 1ª chamada (pai): dispara spawn
            return Completion(text='```json\n{"tool": "spawn", "args": {"goal": "subtask"}}\n```',
                              provider="p", model="m")
        return Completion(text='```json\n{"tool": "respond", "args": {"message": "ok"}}\n```',
                          provider="p", model="m")
    monkeypatch.setattr(prov, "complete_messages_ex", _fake)
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: _fake(*a, **k).text)

    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})
    t = run_task(cfg, tmp_path, "delega isso", surface="cli")
    assert t.state == TaskState.COMPLETE

    assert len(harnesses) == 2, "esperava 2 harnesses (pai + 1 subagente spawnado)"
    parent_registry, child_registry = harnesses[0]["registry"], harnesses[1]["registry"]

    # (d) pai (depth 0) mantém o toolset COMPLETO
    for tool in ("spawn", "spawn_jobs", "manage_skill", "install_skill"):
        assert tool in parent_registry, f"pai perdeu {tool} (regressão)"

    # (a) filho (spawnado) NÃO tem delegação nem autoria/instalação de skill
    for tool in ("spawn", "spawn_jobs", "manage_skill", "install_skill"):
        assert tool not in child_registry, f"filho herdou {tool} — anti-recursão/anti-mutação furada"

    # (b) filho ainda faz trabalho real
    for tool in ("read_file", "write_file", "run_shell", "search_files"):
        assert tool in child_registry, f"filho perdeu {tool} — restrição forte demais"


def test_spawn_depth_cap_still_enforced(tmp_path, monkeypatch):
    """(c) defesa em camadas: o teto de profundidade (depth>=2) continua recusando spawn — o novo
    registry_filter não é a ÚNICA barreira contra recursão explosiva."""
    import okami.llm.providers as prov
    from okami.config import build_config
    from okami.core import TaskState
    from okami.llm.usage import Completion
    from okami.runner import run_task

    calls = {"n": 0}

    def _fake(cfg, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:               # tenta spawnar; se o teto segurar, o harness só vê a recusa
            return Completion(text='```json\n{"tool": "spawn", "args": {"goal": "subtask"}}\n```',
                              provider="p", model="m")
        return Completion(text='```json\n{"tool": "respond", "args": {"message": "limite respeitado"}}\n```',
                          provider="p", model="m")
    monkeypatch.setattr(prov, "complete_messages_ex", _fake)
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: _fake(*a, **k).text)

    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})
    # depth=2 simula um neto tentando spawnar de novo — _spawn tem que recusar SEM recursar.
    t = run_task(cfg, tmp_path, "tenta spawnar no fundo", surface="cli", depth=2)
    assert t.state == TaskState.COMPLETE
    assert calls["n"] == 2, "só 2 chamadas de geração (pai) — nenhuma recursão de run_task aconteceu"
