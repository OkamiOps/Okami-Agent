"""Regressões da revisão adversarial da pesquisa #5 — bugs confirmados nos reviews."""
from __future__ import annotations

import json

import pytest
import yaml

from okami.core.tools.base import ToolContext
from okami.core.tools.patch import ApplyPatch, apply_hunks, PatchError


def _ctx(tmp_path, read=()):
    c = ToolContext(workspace=tmp_path)
    c.read_files.update(read)
    return c


def _patch(*lines):
    return "*** Begin Patch\n" + "\n".join(lines) + "\n*** End Patch"


# ── patch #7: fuzzy strip NÃO pode casar no bloco errado silenciosamente ──────────
def test_apply_hunks_ambiguous_fuzzy_refuses():
    # dois blocos idênticos a menos de indentação; hunk com indentação divergente é AMBÍGUO no nível
    # strip → tem que ERRAR (não escolher um silenciosamente).
    text = "def a():\n    x = 1\n    return x\ndef b():\n        x = 1\n        return x\n"
    with pytest.raises(PatchError):
        apply_hunks(text, [[(" ", "  x = 1"), ("-", "  return x"), ("+", "  return y")]], "f.py")


def test_apply_hunks_unique_fuzzy_still_works():
    # 1 só bloco — fuzzy (whitespace divergente) casa sem ambiguidade
    text = "inicio()  \n    velho()   \nfim()\n"
    out = apply_hunks(text, [[(" ", "inicio()"), ("-", "    velho()"), ("+", "    novo()")]], "f.py")
    assert "novo()" in out and "velho()" not in out


# ── patch #8: FASE 2 não pode deixar estado parcial num erro no meio ──────────────
def test_patch_rolls_back_on_midwrite_failure(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("um\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("dois\n", encoding="utf-8")
    calls = {"n": 0}
    from okami.core.file_safety import write_text_atomic as _wta

    def flaky(p, content):
        calls["n"] += 1
        if calls["n"] == 2:                              # falha no 2º arquivo
            raise OSError("disco cheio simulado")
        return _wta(p, content)

    monkeypatch.setattr("okami.core.file_safety.write_text_atomic", flaky)
    res = ApplyPatch().run({"patch": _patch(
        "*** Update File: a.txt", "-um", "+UM",
        "*** Update File: b.txt", "-dois", "+DOIS")}, _ctx(tmp_path, read=["a.txt", "b.txt"]))
    assert not res.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "um\n"   # 1º RESTAURADO (rollback)


def test_patch_move_refuses_overwrite_unread_dst(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("conteúdo importante\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch(
        "*** Update File: a.txt", "*** Move to: b.txt", "-a", "+A")}, _ctx(tmp_path, read=["a.txt"]))
    assert not res.ok
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "conteúdo importante\n"  # não sobrescrito


# ── billing #3: 429 de rate-limit que MENCIONA "billing" não vira billing ─────────
def test_rate_limit_mentioning_billing_is_not_billing():
    from okami.llm.errors import classify

    class E(Exception):
        status_code = 429

    ce = classify(E("You hit your rate limit. For info on rate limits and billing, see docs."))
    assert ce.reason == "rate_limit"                     # não billing → park 1h, não 6h


def test_real_billing_still_detected():
    from okami.llm.errors import classify
    assert classify(Exception("You exceeded your current quota, check your billing details")).reason == "billing"
    assert classify(Exception("Your credit balance is too low")).reason == "billing"


# ── curator #8: .usage.json escrito atomicamente (não corrompe num crash) ─────────
def test_usage_write_is_atomic(tmp_path, monkeypatch):
    from okami.learning import curator as cur
    cur.record_skill_use(tmp_path, "s1")
    # durante o write, simula crash ANTES do replace → arquivo final intacto (não truncado)
    import os
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    try:
        cur._set_state(tmp_path, "s1", "stale")
    except OSError:
        pass
    monkeypatch.setattr(os, "replace", real_replace)
    data = json.loads((tmp_path / cur.USAGE_FILE).read_text())  # parseável (não truncado)
    assert "s1" in data


# ── curator #9: umbrella não pode colidir com skill protegida ────────────────────
def test_validate_plan_rejects_umbrella_colliding_protected(tmp_path):
    from okami.learning import curator as cur

    def mk(name, **meta):
        d = tmp_path / name
        d.mkdir()
        m = {"name": name, "description": name, **meta}
        (d / "SKILL.md").write_text("---\n" + yaml.safe_dump(m) + "---\n## Quando\nx\n## Como\ny\n",
                                    encoding="utf-8")

    mk("git-workflow", origin="")                        # curada (sem origin agent) = protegida
    mk("debug-x", origin="agent")
    plan = {"merges": [{"umbrella": "git-workflow", "description": "d",
                        "absorb": ["debug-x"], "body": "## Quando\na\n## Como\nb"}], "archive": []}
    _, errors = cur.validate_plan(plan, tmp_path)
    assert any("git-workflow" in e for e in errors)      # rejeitado: colide com skill protegida


# ── harness #1: trabalho longo legítimo NÃO morre por 2 compactações distantes ───
def test_thrash_does_not_fire_when_progress_between_compactions(tmp_path, monkeypatch):
    """Compactação de baixo ganho, MUITO trabalho real, e outra compactação de baixo ganho —
    com progresso (escrita) no meio — NÃO pode disparar o anti-thrash (era o falso-positivo que
    matava trabalho longo legítimo)."""
    import okami.core.harness.loop as loop_mod
    from okami.core import Task
    from okami.core.harness import Harness
    from okami.core.harness.models import Budget

    (tmp_path / "f.txt").write_text("x\n", encoding="utf-8")
    script = iter([
        '{"tool": "read_file", "args": {"path": "f.txt"}}',     # turno 1 (vai compactar, baixo ganho)
        '{"tool": "write_file", "args": {"path": "out.txt", "content": "feito"}}',  # PROGRESSO real
        '{"tool": "read_file", "args": {"path": "f.txt"}}',     # turno 3 (compacta de novo, baixo ganho)
        '{"tool": "task_complete", "args": {"summary": "ok"}}',
    ])
    # sempre acima do teto → compacta todo turno; compact rende pouco (baixo ganho sempre)
    monkeypatch.setattr(loop_mod._compaction, "estimate_chars", lambda m: 30000)
    monkeypatch.setattr(loop_mod._compaction, "prune_observations", lambda m, **k: (m, 0))
    monkeypatch.setattr(loop_mod._compaction, "compact", lambda m, mem, **k: (m, 0))  # 0% ganho
    h = Harness(generate=lambda m, s: next(script), task=Task(goal="faça"), workspace=tmp_path,
                budget=Budget(max_context_chars=24000))
    res = h.run()
    assert res.state.name == "COMPLETE", f"trabalho legítimo morto pelo anti-thrash: {res.reason}"


# ── harness #2b: re-emissão de AÇÃO truncada tem teto (não spina até max_total_turns) ──
def test_truncated_action_reemit_is_capped(tmp_path):
    from okami.core import Task
    from okami.core.harness import Harness
    from okami.core.harness.models import Budget
    from okami.llm.usage import Completion
    calls = {"n": 0}

    def gen(messages, schema):                          # SEMPRE re-emite write_file truncado
        calls["n"] += 1
        return Completion(text='```json\n{"tool":"write_file","args":{"path":"a","content":"aaaa',
                          finish_reason="length")

    h = Harness(generate=gen, task=Task(goal="x"), workspace=tmp_path,
                budget=Budget(max_total_turns=1000))
    res = h.run()
    assert res.state.name in ("FAILED", "BLOCKED")
    assert calls["n"] < 30, f"sem teto: {calls['n']} chamadas (spinou até o backstop de turnos)"


def test_truncated_report_continues_and_completes(tmp_path):
    # fluxo REAL: respond com message longa é UM json truncado → continua → completa (Case A do review)
    from okami.core import Task
    from okami.core.harness import Harness
    from okami.llm.usage import Completion
    parts = iter([
        Completion(text='{"tool":"respond","args":{"message":"Relatorio parte 1 ',
                   finish_reason="length"),
        Completion(text='e a conclusao final aqui FIM"}}'),
    ])
    h = Harness(generate=lambda m, s: next(parts), task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    assert "parte 1" in (res.result or "") and "FIM" in (res.result or "")   # parcial preservado


# ── caching #5: cache_control vai no último bloco de TEXTO, não numa imagem ───────
def test_prompt_caching_targets_text_not_image():
    from okami.llm.providers import apply_prompt_caching
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "descreva"},
        {"type": "image_url", "image_url": {"url": "data:..."}}]}]
    out = apply_prompt_caching(msgs, "anthropic/claude-sonnet-4-6")
    parts = out[0]["content"]
    assert parts[0].get("cache_control"), "cache_control deveria ir no bloco de TEXTO"
    assert not parts[1].get("cache_control"), "não pode ir no bloco de imagem"


# ── empty-nudge: conteúdo multimodal (list) não quebra a alternância ──────────────
def test_empty_nudge_preserves_alternation_with_vision():
    from okami.llm.providers import _with_empty_nudge
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": [{"type": "text", "text": "veja"},
                                         {"type": "image_url", "image_url": {"url": "x"}}]}]
    out = _with_empty_nudge(msgs)
    roles = [m["role"] for m in out]
    assert roles == ["system", "user"]                   # NÃO criou 2ª user (era o bug)
    flat = str(out[-1]["content"])
    assert "VAZIA" in flat                                # nudge entrou na própria user


def test_thrash_still_fires_without_progress(tmp_path, monkeypatch):
    """Sem nenhum progresso (só compacta e re-planeja), o anti-thrash AINDA dispara."""
    import okami.core.harness.loop as loop_mod
    from okami.core import Task
    from okami.core.harness import Harness
    from okami.core.harness.models import Budget
    monkeypatch.setattr(loop_mod._compaction, "estimate_chars", lambda m: 30000)
    monkeypatch.setattr(loop_mod._compaction, "prune_observations", lambda m, **k: (m, 0))
    monkeypatch.setattr(loop_mod._compaction, "compact", lambda m, mem, **k: (m, 0))
    h = Harness(generate=lambda m, s: '{"tool": "list_dir", "args": {"path": "."}}',
                task=Task(goal="x"), workspace=tmp_path, budget=Budget(max_context_chars=24000))
    res = h.run()
    assert res.state.name == "FAILED" and "/new" in (res.reason or "")
