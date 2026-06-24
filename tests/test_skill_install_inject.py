"""Skills (hunt#2): (a) _support_files_note avisa '+N' quando trunca em 30 (senão o agente acha que viu a
lista completa e perde um arquivo crítico); (b) InstallSkill que falha na INJEÇÃO em memória (parse/encoding,
inclui UnicodeDecodeError que não é OSError) não crasha, avisa, e NÃO marca effect=True (senão o watchdog é
enganado e use_skill falha → mini-loop)."""
from __future__ import annotations

from types import SimpleNamespace

from okami.core.tools.agentic import InstallSkill, UseSkill


# ------------------------------------------------------------- (a) +N marker
def test_support_files_note_marks_overflow(tmp_path):
    sd = tmp_path / "myskill"
    (sd / "scripts").mkdir(parents=True)
    for i in range(35):
        (sd / "scripts" / f"f{i:02d}.txt").write_text("x", encoding="utf-8")
    note = UseSkill._support_files_note("myskill", str(sd))
    assert "+5" in note                                  # 35 - 30 listados = 5 a mais, sinalizado


def test_support_files_note_no_marker_when_few(tmp_path):
    sd = tmp_path / "s"
    (sd / "scripts").mkdir(parents=True)
    (sd / "scripts" / "a.txt").write_text("x", encoding="utf-8")
    note = UseSkill._support_files_note("s", str(sd))
    assert "mais" not in note and "+0" not in note


# ------------------------------------------------------------- (b) injeção que falha
def test_install_injection_failure_no_crash_no_false_effect(tmp_path, monkeypatch):
    import okami.skills.install as inst
    import okami.skills as skills_mod

    fake = SimpleNamespace(ok=True, installed=["foo"], reason="", kind="git", trust="t",
                           verdict="INFO", deps=[])
    monkeypatch.setattr(inst, "install_from_source", lambda *a, **k: fake)

    def boom(_p):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "ruim")   # NÃO é OSError
    monkeypatch.setattr(skills_mod, "parse_skill", boom)

    ctx = SimpleNamespace(skills={}, workspace=str(tmp_path), home=tmp_path,
                          skills_dir=str(tmp_path), __dict__={})
    r = InstallSkill().run({"source": "owner/repo"}, ctx)
    assert r.effect is False                              # injeção falhou → NÃO finge progresso (anti mini-loop)
    assert "INVISÍVEL" in r.output or "invisível" in r.output.lower()
    assert "foo" not in ctx.skills                        # não entrou no catálogo (mas não crashou)
