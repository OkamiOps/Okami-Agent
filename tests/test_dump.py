"""#9: `okami dump` — uma tela humano-colável p/ bug report (home/commit/skills/providers/canais),
segredo REDIGIDO. Reusa o que doctor/status já coletam; formato p/ colar em issue/chat."""
from __future__ import annotations


from types import SimpleNamespace


def test_build_dump_has_sections_and_no_secret(tmp_path):
    from okami.core.dump import build_dump
    cfg = SimpleNamespace(
        providers={"codex": {"model": "openai-codex/gpt-5", "api_key": "sk-supersecret0123456789abcd"}},
        channels={"telegram": {"token": "12345:AAsegredodobotaqui"}})
    out = build_dump(cfg, home=tmp_path)
    assert "HOME" in out and "providers" in out.lower() and "codex" in out
    assert "sk-supersecret0123456789abcd" not in out      # segredo do provider NÃO vaza
    assert "AAsegredodobotaqui" not in out                # token do canal NÃO vaza


def test_build_dump_lists_skill_count(tmp_path):
    from okami.core.dump import build_dump
    sk = tmp_path / "skills" / "deploy"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: deploy\n---\nx", encoding="utf-8")
    out = build_dump(SimpleNamespace(providers={"p": {"model": "m"}}, channels={}),
                     home=tmp_path, skills_dir=tmp_path / "skills")
    assert "skills" in out.lower()
