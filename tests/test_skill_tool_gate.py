"""Gate de skill por tool disponível (paridade Hermes `_skill_should_show`, prompt_builder.py:1387-1414):
`requires_tools` esconde a skill quando a tool NÃO está no registry; `fallback_for_tools` esconde quando
a tool JÁ está (a skill é o plano B). `available_tools=None` (retrocompat) não filtra nada."""
from __future__ import annotations

from okami import skills as skillmod


def _write(tmp_path, name, *, requires_tools=(), fallback_for_tools=()):
    d = tmp_path / name
    d.mkdir(parents=True)
    import yaml as _yaml
    meta = {"name": name, "description": "d"}
    if requires_tools:
        meta["requires_tools"] = list(requires_tools)
    if fallback_for_tools:
        meta["fallback_for_tools"] = list(fallback_for_tools)
    (d / "SKILL.md").write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True) + "---\ncorpo",
                                encoding="utf-8")


def test_parse_skill_reads_tool_conditions(tmp_path):
    _write(tmp_path, "precisa-de-browser", requires_tools=["browser_navigate"])
    _write(tmp_path, "grep-fallback", fallback_for_tools=["ripgrep"])
    sks = {s.name: s for s in skillmod.load_skills(tmp_path)}
    assert sks["precisa-de-browser"].requires_tools == ["browser_navigate"]
    assert sks["grep-fallback"].fallback_for_tools == ["ripgrep"]


def test_no_conditions_always_visible(tmp_path):
    _write(tmp_path, "sem-condicao")
    sk = skillmod.load_skills(tmp_path)[0]
    assert skillmod.skill_matches_tools(sk, None) is True
    assert skillmod.skill_matches_tools(sk, set()) is True
    assert skillmod.skill_matches_tools(sk, {"anything"}) is True


def test_requires_tools_hides_when_tool_absent(tmp_path):
    _write(tmp_path, "precisa-de-browser", requires_tools=["browser_navigate"])
    sk = skillmod.load_skills(tmp_path)[0]
    assert skillmod.skill_matches_tools(sk, {"terminal"}) is False           # ausente → some
    assert skillmod.skill_matches_tools(sk, {"browser_navigate"}) is True    # presente → aparece
    assert skillmod.skill_matches_tools(sk, None) is True                    # sem filtro → sempre aparece


def test_fallback_for_tools_hides_when_primary_present(tmp_path):
    _write(tmp_path, "grep-fallback", fallback_for_tools=["ripgrep"])
    sk = skillmod.load_skills(tmp_path)[0]
    assert skillmod.skill_matches_tools(sk, {"ripgrep"}) is False            # tool primária JÁ disponível → some
    assert skillmod.skill_matches_tools(sk, {"terminal"}) is True            # ausente → skill é o plano B, aparece
    assert skillmod.skill_matches_tools(sk, None) is True


def test_visible_skills_wires_tool_gate(tmp_path):
    _write(tmp_path, "precisa-de-browser", requires_tools=["browser_navigate"])
    _write(tmp_path, "sempre-visivel")
    sks = skillmod.load_skills(tmp_path)
    only_terminal = skillmod.visible_skills(sks, os_name="linux", available_tools={"terminal"})
    names = {s.name for s in only_terminal}
    assert names == {"sempre-visivel"}                                      # a que precisa de browser some

    with_browser = skillmod.visible_skills(sks, os_name="linux",
                                            available_tools={"terminal", "browser_navigate"})
    assert {s.name for s in with_browser} == {"precisa-de-browser", "sempre-visivel"}

    # available_tools=None (default) → não filtra por tool, só plataforma/ambiente (retrocompat)
    unfiltered = skillmod.visible_skills(sks, os_name="linux")
    assert {s.name for s in unfiltered} == {"precisa-de-browser", "sempre-visivel"}
