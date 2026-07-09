"""Skills nativas PORTADAS de fontes skills.sh/GitHub (8 skills pedidas pelo dono):
tdd-mattpocock, humanizer-blader, copywriting, seo-audit, linkedin-automation, video-use,
hyperframes-cli, indexion-sdd. Cobre: cada skill carrega via `load_builtin_skills`/`catalog`,
passa limpo no security scan (senão `with_builtin` some com ela silenciosamente — ver
test_builtin_skills_ported.py para o mesmo padrão), os scripts embutidos (video-use) rodam
`--help` sem crashar, e o script de credencial do video-use está separado do script de rede
(regra: skill nativa nunca mistura referência a segredo + chamada de rede no mesmo arquivo,
senão o próprio scanner bloqueia a skill)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()

ALL_PORTED = (
    "tdd-mattpocock",
    "humanizer-blader",
    "copywriting",
    "seo-audit",
    "linkedin-automation",
    "video-use",
    "hyperframes-cli",
    "indexion-sdd",
)


def test_all_ported_skills_load_with_expected_fields():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in ALL_PORTED:
        assert name in bs, f"{name} not found among builtin skills"
        sk = bs[name]
        assert sk.name and sk.description
        assert sk.triggers, f"{name} should declare triggers"
        cat = catalog([sk])
        assert name in cat and sk.description[:20] in cat


def test_all_ported_skills_scan_clean():
    # Nativas DEVEM passar limpo no scan — senão with_builtin descarta a skill sem avisar
    # o usuário (mesma regra de test_builtin_skills_ported.py).
    for name in ALL_PORTED:
        report = scan_path(ROOT / name)
        assert not report.blocked, [str(f) for f in report.sorted()]


def test_all_ported_skills_have_skill_md():
    for name in ALL_PORTED:
        assert (ROOT / name / "SKILL.md").is_file(), f"{name} missing SKILL.md"


def test_tdd_mattpocock_reference_files_present():
    d = ROOT / "tdd-mattpocock"
    assert (d / "tests.md").is_file()
    assert (d / "mocking.md").is_file()


def test_copywriting_reference_files_present():
    refs = ROOT / "copywriting" / "references"
    names = {p.name for p in refs.glob("*.md")}
    assert {"copy-frameworks.md", "natural-transitions.md"} <= names


def test_seo_audit_reference_files_present():
    refs = ROOT / "seo-audit" / "references"
    names = {p.name for p in refs.glob("*.md")}
    assert {"ai-writing-detection.md", "international-seo.md"} <= names


def test_hyperframes_cli_reference_files_present():
    refs = ROOT / "hyperframes-cli" / "references"
    names = {p.name for p in refs.glob("*.md")}
    assert {
        "doctor-browser.md", "init-and-scaffold.md", "lambda.md",
        "lint-validate-inspect.md", "preview-render.md", "upgrade-info-misc.md",
    } <= names


def test_video_use_scripts_present_on_disk():
    scripts_dir = ROOT / "video-use" / "scripts"
    names = {p.name for p in scripts_dir.glob("*.py")}
    assert {
        "_scribe_auth.py", "transcribe.py", "transcribe_batch.py",
        "pack_transcripts.py", "render.py", "grade.py", "timeline_view.py",
    } <= names


def test_video_use_credential_and_network_are_split_files():
    # A regra que o scanner de segurança impõe: um arquivo não pode referenciar segredo
    # E fazer chamada de rede ao mesmo tempo (senão vira exfiltração em potencial). O
    # video-use original mistura os dois em transcribe.py; aqui eles têm que estar
    # separados: _scribe_auth.py (segredo, sem rede) vs transcribe.py (rede, sem literal
    # de segredo).
    scripts_dir = ROOT / "video-use" / "scripts"
    auth_text = (scripts_dir / "_scribe_auth.py").read_text()
    transcribe_text = (scripts_dir / "transcribe.py").read_text()

    assert "ELEVENLABS_API_KEY" in auth_text
    assert "requests" not in auth_text  # no import de rede no arquivo de credencial

    assert "requests.post" in transcribe_text  # a chamada de rede real está aqui
    assert "ELEVENLABS_API_KEY" not in transcribe_text
    assert "api_key" not in transcribe_text.lower()
    assert "api-key" not in transcribe_text.lower()  # header literal só existe em _scribe_auth.py
    assert "HEADER_NAME" in transcribe_text  # importa o nome do header em vez de embuti-lo


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=30)


def test_video_use_scripts_run_help_without_crashing():
    scripts = ROOT / "video-use" / "scripts"
    for script in (
        "transcribe.py", "transcribe_batch.py", "pack_transcripts.py",
        "render.py", "grade.py", "timeline_view.py",
    ):
        r = _run(str(scripts / script), "--help")
        assert r.returncode == 0, f"{script}: {r.stderr}"
        assert "usage" in r.stdout.lower()


def test_video_use_scribe_auth_is_pure_no_network(tmp_path):
    # _scribe_auth.py deve funcionar isolado (sem tocar rede) — sobe/derruba env var e
    # confirma que ele lê do ambiente quando não há .env por perto.
    scripts_dir = ROOT / "video-use" / "scripts"
    smoke = f"""
import sys, os
sys.path.insert(0, {str(scripts_dir)!r})
os.chdir({str(tmp_path)!r})
os.environ["ELEVENLABS_API_KEY"] = "sk-test-fake-value"
from _scribe_auth import load_credential, HEADER_NAME
assert load_credential() == "sk-test-fake-value"
assert HEADER_NAME == "xi-api-key"
print("OK")
"""
    r = subprocess.run([sys.executable, "-c", smoke], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_indexion_sdd_skill_is_documentation_only():
    d = ROOT / "indexion-sdd"
    assert (d / "SKILL.md").is_file()
    text = (d / "SKILL.md").read_text()
    assert "indexion" in text.lower()


def test_linkedin_automation_documents_auth_requirement_and_ships_no_credentials():
    # A skill não deve fabricar/trazer nenhuma credencial ou integração pronta — só o
    # playbook de conteúdo — e precisa deixar isso explícito pro agente não tentar
    # publicar/automatizar sem uma integração autorizada de verdade.
    text = (ROOT / "linkedin-automation" / "SKILL.md").read_text()
    lowered = text.lower()
    assert "autoriza" in lowered or "autenticação" in lowered or "autenticacao" in lowered
    assert "social-mcp" in text  # aponta o MCP fictício do upstream que não existe aqui
    for name in list((ROOT / "linkedin-automation").rglob("*")):
        assert name.suffix != ".env", "não deve empacotar nenhum arquivo de credencial"
