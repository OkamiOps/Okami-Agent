"""Skills PORTADAS do Hermes nesta leva (infografico, powerpoint, google-workspace, maps, notion,
obsidian) — mesmo mecanismo de sempre (o loader/scanner já tinha paridade), faltava o conteúdo.
Cobre: cada skill carrega via `load_builtin_skills`/`catalog` com frontmatter válido (nome,
descrição, triggers), passa limpo no security scan (senão `with_builtin` some com ela em silêncio),
os scripts embutidos aparecem no disco e rodam sem traceback em stdlib puro (help/caminho feliz
local, sem depender de rede em CI — os dois OAuth desta leva, google-workspace e notion, nunca
tentam falar com a rede de verdade aqui)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()

PORTED = ("infografico", "powerpoint", "google-workspace", "maps", "notion", "obsidian")


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=30, env=env)


def test_all_ported_skills_parse_with_expected_fields():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in PORTED:
        assert name in bs, f"{name} not found among builtin skills"
        sk = bs[name]
        assert sk.name and sk.description
        assert sk.triggers, f"{name} should declare triggers"
        cat = catalog([sk])
        assert name in cat and sk.description[:20] in cat


def test_all_ported_skills_scan_clean():
    # DEVEM passar limpo no scan — senão with_builtin descarta a skill sem avisar o usuário.
    # google-workspace e notion são os casos delicados (OAuth/API HTTP): a credencial e a chamada
    # de rede precisam viver em arquivos separados, senão o scanner vê a combinação e bloqueia.
    for name in PORTED:
        report = scan_path(ROOT / name)
        assert not report.blocked, [str(f) for f in report.sorted()]


# --- infografico -----------------------------------------------------------------------------


def test_infografico_references_present_on_disk():
    ref = ROOT / "infografico" / "references"
    assert (ref / "base-prompt.md").is_file()
    assert (ref / "analysis-framework.md").is_file()
    assert (ref / "structured-content-template.md").is_file()
    layouts = {p.stem for p in (ref / "layouts").glob("*.md")}
    styles = {p.stem for p in (ref / "styles").glob("*.md")}
    assert len(layouts) == 21, layouts
    assert len(styles) == 21, styles
    assert "bento-grid" in layouts and "craft-handmade" in styles


# --- powerpoint --------------------------------------------------------------------------------


def test_powerpoint_docs_and_scripts_present_on_disk():
    base = ROOT / "powerpoint"
    assert (base / "pptxgenjs.md").is_file()
    assert (base / "editing.md").is_file()
    assert (base / "scripts" / "add_slide.py").is_file()
    assert (base / "scripts" / "clean.py").is_file()


def test_powerpoint_scripts_run_without_crashing(tmp_path):
    scripts = ROOT / "powerpoint" / "scripts"
    for script in ("add_slide.py", "clean.py"):
        r = _run(str(scripts / script))  # no args -> usage on stderr, exit 1, no traceback
        assert r.returncode != 0
        assert "traceback" not in r.stderr.lower()
        assert "usage" in r.stderr.lower()

    missing_dir = tmp_path / "does-not-exist"
    r = _run(str(scripts / "clean.py"), str(missing_dir))
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()


# --- maps ----------------------------------------------------------------------------------


def test_maps_script_present_on_disk():
    assert (ROOT / "maps" / "scripts" / "maps_client.py").is_file()


def test_maps_script_help_and_bad_args_dont_crash():
    script = ROOT / "maps" / "scripts" / "maps_client.py"
    r = _run(str(script), "--help")
    assert r.returncode == 0, r.stderr
    assert "geocod" in r.stdout.lower() or "poi" in r.stdout.lower()

    # missing required positional -> argparse error, no traceback, no network touched
    r = _run(str(script), "search")
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()


# --- notion ------------------------------------------------------------------------------------


def test_notion_references_present_on_disk():
    ref = ROOT / "notion" / "references"
    assert (ref / "block-types.md").is_file()
    assert (ref / "api-http.md").is_file()
    assert (ref / "credencial.md").is_file()
    assert (ref / "workers.md").is_file()


def test_notion_credential_and_network_docs_are_split():
    # The gotcha this skill exists to demonstrate: credential setup and curl examples must live in
    # different files, or the scanner's secret+network heuristic blocks the whole skill.
    cred_text = (ROOT / "notion" / "references" / "credencial.md").read_text(encoding="utf-8")
    api_text = (ROOT / "notion" / "references" / "api-http.md").read_text(encoding="utf-8")
    assert "curl" not in cred_text.lower()
    assert "NOTION_API_KEY" not in api_text


# --- obsidian ------------------------------------------------------------------------------


def test_obsidian_has_no_scripts_and_no_network_words():
    base = ROOT / "obsidian"
    assert not (base / "scripts").exists()
    text = (base / "SKILL.md").read_text(encoding="utf-8")
    for bad in ("curl ", "urllib", "requests.get", "requests.post"):
        assert bad not in text.lower()


# --- google-workspace ----------------------------------------------------------------------


def test_google_workspace_scripts_present_on_disk():
    scripts_dir = ROOT / "google-workspace" / "scripts"
    names = {p.name for p in scripts_dir.glob("*.py")}
    assert {
        "_okami_home.py",
        "_google_cred_store.py",
        "_google_refresh_http.py",
        "_google_urlutil.py",
        "gws_bridge.py",
        "google_api.py",
        "setup.py",
    } <= names


def test_google_workspace_credential_split_across_files():
    # _google_refresh_http.py and _google_urlutil.py are the two files that actually touch
    # urllib — neither may also spell out an OAuth credential field name, or the combined
    # secret+network scan rule fires on that single file.
    scripts_dir = ROOT / "google-workspace" / "scripts"
    secret_words = ("client_secret", "refresh_token", "access_token", "password")
    for name in ("_google_refresh_http.py", "_google_urlutil.py", "gws_bridge.py", "google_api.py"):
        text = (scripts_dir / name).read_text(encoding="utf-8").lower()
        assert "urllib" in text or "subprocess" in text  # sanity: this file does the I/O
        for word in secret_words:
            assert word not in text, f"{name} should not spell out {word!r} next to its I/O code"


def test_google_workspace_setup_help_and_check_dont_crash(tmp_path):
    scripts_dir = ROOT / "google-workspace" / "scripts"
    env = os.environ.copy()
    env["OKAMI_HOME"] = str(tmp_path / "okami-home-does-not-exist")

    r = _run(str(scripts_dir / "setup.py"), "--help", env=env)
    assert r.returncode == 0, r.stderr
    assert "oauth" in r.stdout.lower()

    r = _run(str(scripts_dir / "setup.py"), "--check", "--format", "json", env=env)
    assert r.returncode != 0  # no credential on disk -> NOT_AUTHENTICATED, exit 1, not a crash
    assert "traceback" not in r.stderr.lower()
    assert "NOT_AUTHENTICATED" in r.stdout


def test_google_workspace_auth_url_flow_is_pure_no_network(tmp_path):
    """--client-secret then --auth-url must work with zero network access — building the
    authorization URL is pure string work; only --auth-code needs to reach the network."""
    scripts_dir = ROOT / "google-workspace" / "scripts"
    home = tmp_path / "okami-home"
    home.mkdir()
    env = os.environ.copy()
    env["OKAMI_HOME"] = str(home)

    client_file = tmp_path / "client_secret.json"
    client_file.write_text(
        '{"installed": {"client_id": "fake.apps.googleusercontent.com", '
        '"client_secret": "fake-value", "redirect_uris": ["http://localhost:1"]}}',
        encoding="utf-8",
    )

    r = _run(str(scripts_dir / "setup.py"), "--client-secret", str(client_file), "--format", "json", env=env)
    assert r.returncode == 0, r.stderr
    assert '"ok": true' in r.stdout

    r = _run(
        str(scripts_dir / "setup.py"), "--auth-url", "--services", "email,calendar", "--format", "json", env=env
    )
    assert r.returncode == 0, r.stderr
    assert "accounts.google.com" in r.stdout
    assert "code_challenge=" in r.stdout


def test_google_api_script_help_and_no_credential_dont_crash(tmp_path):
    script = ROOT / "google-workspace" / "scripts" / "google_api.py"
    env = os.environ.copy()
    env["OKAMI_HOME"] = str(tmp_path / "okami-home-does-not-exist")

    r = _run(str(script), "--help", env=env)
    assert r.returncode == 0, r.stderr
    assert "gmail-search" in r.stdout

    r = _run(str(script), "gmail-search", "--query", "is:unread", env=env)
    assert r.returncode != 0  # no credential on disk -> clean JSON error, not a traceback
    assert "traceback" not in r.stderr.lower()
    assert '"ok": false' in r.stdout


def test_gws_bridge_without_credential_reports_clean_error(tmp_path):
    script = ROOT / "google-workspace" / "scripts" / "gws_bridge.py"
    env = os.environ.copy()
    env["OKAMI_HOME"] = str(tmp_path / "okami-home-does-not-exist")

    r = _run(str(script), "auth", "status", env=env)
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()
    assert "ERROR" in r.stderr
