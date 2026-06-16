"""#11 Onda 4: skills — config no frontmatter, gating por plataforma/ambiente, dispatch de bundle."""
from __future__ import annotations


def _write_skill(d, name, frontmatter="", body="## Como\nfaça X"):
    p = d / name
    p.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\n{frontmatter}---\n" if frontmatter or True else ""
    (p / "SKILL.md").write_text(f"{fm}{body}\n", encoding="utf-8")
    return p / "SKILL.md"


# ── config no frontmatter (metadata.okami.config) ──
def test_extract_skill_config_vars(tmp_path):
    from okami.skills import extract_skill_config_vars, parse_skill
    _write_skill(tmp_path, "wiki", "okami:\n  config:\n    - key: wiki.path\n      description: caminho do wiki\n      prompt: Onde fica o wiki?\n")
    sk = parse_skill(tmp_path / "wiki" / "SKILL.md")
    cfgs = extract_skill_config_vars(sk)
    assert cfgs and cfgs[0]["key"] == "wiki.path" and "prompt" in cfgs[0]


def test_missing_skill_config(tmp_path):
    from okami.skills import missing_skill_config, parse_skill
    _write_skill(tmp_path, "wiki", "okami:\n  config:\n    - key: wiki.path\n      description: x\n")
    sk = parse_skill(tmp_path / "wiki" / "SKILL.md")
    assert "wiki.path" in {m["key"] for m in missing_skill_config([sk], {})}        # não configurado → falta
    assert missing_skill_config([sk], {"wiki.path": "/x"}) == []                      # configurado → ok


# ── gating por plataforma/ambiente ──
def test_skill_platform_gating(tmp_path):
    from okami.skills import parse_skill, skill_matches_platform
    _write_skill(tmp_path, "mac-only", "platforms: [darwin]\n")
    sk = parse_skill(tmp_path / "mac-only" / "SKILL.md")
    assert skill_matches_platform(sk, "darwin") is True
    assert skill_matches_platform(sk, "linux") is False
    # skill SEM declaração casa qualquer plataforma
    _write_skill(tmp_path, "any", "")
    assert skill_matches_platform(parse_skill(tmp_path / "any" / "SKILL.md"), "linux") is True


def test_skill_environment_gating(tmp_path):
    from okami.skills import parse_skill, skill_matches_environment
    _write_skill(tmp_path, "docker-only", "environments: [docker]\n")
    sk = parse_skill(tmp_path / "docker-only" / "SKILL.md")
    assert skill_matches_environment(sk, {"docker"}) is True
    assert skill_matches_environment(sk, set()) is False         # ambiente inativo → escondido do índice


def test_visible_skills_filters_catalog(tmp_path):
    from okami.skills import parse_skill, visible_skills
    _write_skill(tmp_path, "mac", "platforms: [darwin]\n")
    _write_skill(tmp_path, "linux", "platforms: [linux]\n")
    _write_skill(tmp_path, "any", "")
    skills = [parse_skill(tmp_path / n / "SKILL.md") for n in ("mac", "linux", "any")]
    names = {s.name for s in visible_skills(skills, os_name="darwin", active_environments=set())}
    assert names == {"mac", "any"}                               # 'linux' escondido no macOS


# ── dispatch de bundle ──
def test_resolve_bundle_to_skills(tmp_path):
    from okami.skills import parse_skill
    from okami.skills.bundles import bundle_invocation_message, resolve_bundle
    bdir = tmp_path / "bundles"
    bdir.mkdir()
    (bdir / "backend.yaml").write_text("skills: [code-review, run-tests]\n", encoding="utf-8")
    _write_skill(tmp_path, "code-review", body="## Como\nrevise")
    _write_skill(tmp_path, "run-tests", body="## Como\nteste")
    _write_skill(tmp_path, "outra", body="## Como\nnão")
    allsk = [parse_skill(tmp_path / n / "SKILL.md") for n in ("code-review", "run-tests", "outra")]
    resolved = resolve_bundle(bdir, "backend", allsk)
    assert {s.name for s in resolved} == {"code-review", "run-tests"}    # só as do bundle, na ordem
    msg = bundle_invocation_message("backend", resolved)
    assert "backend" in msg and "code-review" in msg and "run-tests" in msg
