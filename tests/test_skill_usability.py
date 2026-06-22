"""Experiência de skill de terceiros (o dono instalou html-to-pdf e 'não funcionou'). Caça e2e ampla:
1) use_skill não dizia ONDE a skill mora → run_shell roda no workspace e 'Cannot find module scripts/x';
2) install não detectava deps (package.json/requirements.txt) → falha em runtime + travamento de 300s.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from okami.core.tools.base import ToolContext
from okami.core.tools.registry import default_registry

_REG = default_registry()


def _skill(root: Path, name: str, *, files: dict[str, str]):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\nRode os scripts.")
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _ctx(skills_dir, catalog):
    return ToolContext(workspace=Path(tempfile.mkdtemp()), registry=_REG,
                       skills=catalog, skills_dir=str(skills_dir), open_fs=True)


def test_use_skill_tells_where_the_skill_lives():
    root = Path(tempfile.mkdtemp())
    _skill(root, "html-to-pdf", files={"scripts/run.js": "console.log(1)"})
    ctx = _ctx(root, {"html-to-pdf": "Rode os scripts."})
    r = _REG["use_skill"].run({"name": "html-to-pdf"}, ctx)
    assert r.ok
    # o agente PRECISA saber o caminho absoluto p/ rodar os scripts (senão 'Cannot find module')
    assert str((root / "html-to-pdf").resolve()) in r.output, r.output[:200]


def test_install_skill_reports_needed_deps():
    """Skill com package.json (puppeteer) → o resultado AVISA que precisa de npm install — em vez de
    instalar 'ok' e estourar em runtime (causa do travamento)."""
    from okami.skills.install import detect_dependencies
    src = Path(tempfile.mkdtemp())
    (src / "SKILL.md").write_text("---\nname: html-to-pdf\ndescription: x\n---\nbody")
    (src / "package.json").write_text('{"dependencies": {"puppeteer": "^22"}}')
    deps = detect_dependencies(src)
    assert any("npm" in d.lower() or "package.json" in d.lower() for d in deps), deps


def test_detect_dependencies_python():
    from okami.skills.install import detect_dependencies
    src = Path(tempfile.mkdtemp())
    (src / "requirements.txt").write_text("requests\n")
    deps = detect_dependencies(src)
    assert any("pip" in d.lower() or "requirements" in d.lower() for d in deps), deps


def test_detect_dependencies_none_when_clean():
    from okami.skills.install import detect_dependencies
    src = Path(tempfile.mkdtemp())
    (src / "SKILL.md").write_text("só markdown, sem deps")
    assert detect_dependencies(src) == []
