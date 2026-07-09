"""Cobertura das skills nativas `apple-notes`, `apple-reminders` (port do Hermes `skills/apple/*`, via
CLIs `memo`/`remindctl`, macOS-only) e `xurl` (port do Hermes `skills/social-media/xurl`, X/Twitter via o
CLI oficial da plataforma).

Segue o padrão de tests/test_design_skills.py: parse via load_builtin_skills, campos obrigatórios
(name/description/triggers/intent_examples), scan de segurança limpo, e checagem de gating por
plataforma (`platforms: [darwin]` nas duas skills Apple; `xurl` roda em linux+macos, sem gating).
"""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills, skill_matches_platform
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()
NAMES = ("apple-notes", "apple-reminders", "xurl")
DARWIN_ONLY = ("apple-notes", "apple-reminders")


def _by_name() -> dict:
    return {sk.name: sk for sk in load_builtin_skills()}


def test_all_three_present_in_builtin_catalog():
    skills = _by_name()
    for name in NAMES:
        assert name in skills, f"skill nativa '{name}' não foi carregada por load_builtin_skills()"


def test_all_three_parse_with_required_fields():
    skills = _by_name()
    for name in NAMES:
        sk = skills[name]
        assert sk.name and sk.description, f"skill {name} sem name/description"
        assert sk.triggers, f"skill {name} sem triggers"
        assert sk.intent_examples, f"skill {name} sem intent_examples"
        cat = catalog([sk])
        assert sk.name in cat and sk.description[:20] in cat


def test_all_three_scan_clean():
    for name in NAMES:
        skill_dir = ROOT / name
        assert (skill_dir / "SKILL.md").exists(), f"{name}/SKILL.md não existe"
        report = scan_path(skill_dir)
        assert not report.blocked, (name, [str(f) for f in report.sorted()])


def test_no_new_skill_ships_shebang_scripts():
    """As três skills são conteúdo puro (markdown) — nenhum script executável, então nenhum arquivo
    deveria abrir com shebang (regra do scanner: shebang + rede == HIGH)."""
    for name in NAMES:
        skill_dir = ROOT / name
        for f in skill_dir.rglob("*"):
            if f.is_file():
                head = f.read_bytes()[:2]
                assert head != b"#!", f"{f} começa com shebang — skill deveria ser conteúdo puro"


def test_apple_skills_declare_darwin_only_platform():
    skills = _by_name()
    for name in DARWIN_ONLY:
        sk = skills[name]
        assert sk.platforms == ["darwin"], f"skill {name} deveria declarar platforms: [darwin], tem {sk.platforms}"
        assert skill_matches_platform(sk, "darwin") is True
        assert skill_matches_platform(sk, "linux") is False
        assert skill_matches_platform(sk, "win32") is False


def test_xurl_skill_has_no_platform_restriction():
    sk = _by_name()["xurl"]
    # xurl roda em linux+macos (Hermes: platforms: [linux, macos]) — sem gating no frontmatter Okami
    # (a skill não declara `platforms`, então casa qualquer OS), documentado no corpo da skill.
    assert skill_matches_platform(sk, "linux") is True
    assert skill_matches_platform(sk, "darwin") is True


def test_apple_notes_skill_documents_memo_dependency():
    sk = _by_name()["apple-notes"]
    assert "memo" in sk.body
    assert "brew" in sk.body.lower()


def test_apple_reminders_skill_documents_remindctl_dependency():
    sk = _by_name()["apple-reminders"]
    assert "remindctl" in sk.body


def test_xurl_skill_documents_credential_safety_rules():
    sk = _by_name()["xurl"]
    body_lower = sk.body.lower()
    assert "auth status" in body_lower
    # regra de segurança mais importante do skill original: nunca cola credencial de volta no chat
    assert "nunca cole" in body_lower or "nunca leia" in body_lower


def test_all_builtin_skills_still_load_without_crash():
    """Guarda-chuva: garante que adicionar as três skills novas não quebrou o carregamento do conjunto
    inteiro de skills nativas. NÃO reescaneia TODAS as skills nativas (test_design_skills.py já cobre
    esse guarda-chuva de segurança separadamente, e um achado pré-existente e não-relacionado em
    `hyperframes-creative` já falha lá — não é escopo desta suíte revalidar skills que não portamos)."""
    bs = load_builtin_skills()
    loaded_names = {sk.name for sk in bs}
    for name in NAMES:
        assert name in loaded_names
