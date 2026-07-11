"""Skills nativas PORTADAS do Hermes (auditoria de conteúdo — mecanismo já tinha paridade, faltava
conteúdo prático): watchers (RSS/GitHub/JSON polling) e stocks (cotação/cripto). Cobre: a skill
carrega via `load_builtin_skills`/`catalog`, passa limpo no security scan (senão `with_builtin` some
com ela silenciosamente), os scripts embutidos aparecem como arquivo de apoio, e cada script roda
sem crashar em stdlib puro (help + um caminho feliz local, sem depender de rede em CI)."""
from __future__ import annotations

import subprocess
import sys

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()


ALL_PORTED = ("watchers", "stocks", "pesquisa-web", "github")


def test_watchers_and_stocks_parse_with_expected_fields():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in ALL_PORTED:
        assert name in bs, f"{name} not found among builtin skills"
        sk = bs[name]
        assert sk.name and sk.description
        assert sk.triggers, f"{name} should declare triggers"
        cat = catalog([sk])
        assert name in cat and sk.description[:20] in cat


def test_watchers_and_stocks_scan_clean():
    # Nativas DEVEM passar limpo no scan — senão with_builtin descarta a skill sem avisar o usuário.
    for name in ALL_PORTED:
        report = scan_path(ROOT / name)
        assert not report.blocked, [str(f) for f in report.sorted()]


def test_watchers_scripts_present_on_disk():
    scripts_dir = ROOT / "watchers" / "scripts"
    names = {p.name for p in scripts_dir.glob("*.py")}
    assert {"_watermark.py", "_gh_auth.py", "watch_rss.py", "watch_http_json.py",
            "watch_github.py"} <= names


def test_stocks_script_present_on_disk():
    assert (ROOT / "stocks" / "scripts" / "stocks_client.py").is_file()


def test_pesquisa_web_scripts_present_on_disk():
    scripts_dir = ROOT / "pesquisa-web" / "scripts"
    names = {p.name for p in scripts_dir.glob("*.py")}
    assert {"_http.py", "search_arxiv.py", "fetch_wikipedia.py"} <= names


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=30)


def test_watcher_scripts_run_without_crashing(tmp_path):
    scripts = ROOT / "watchers" / "scripts"
    env_dir = tmp_path / "watcher-state"
    for script in ("watch_rss.py", "watch_http_json.py", "watch_github.py"):
        r = _run(str(scripts / script), "--help")
        assert r.returncode == 0, r.stderr
        assert "usage" in r.stdout.lower()

    # Caminho feliz local, sem rede: watermark grava/le e dedup funciona (o que os watchers usam por
    # baixo dos panos) — evita depender de um endpoint externo estar de pé em CI.
    smoke = f"""
import sys, os
sys.path.insert(0, {str(scripts)!r})
os.environ["WATCHER_STATE_DIR"] = {str(env_dir)!r}
from _watermark import Watermark, format_items_as_markdown
wm = Watermark.load("t")
assert wm.filter_new([{{"id": "1", "title": "a"}}], id_key="id") == []   # 1a run: baseline, nada emitido
wm.save()
wm2 = Watermark.load("t")
new = wm2.filter_new([{{"id": "1"}}, {{"id": "2", "title": "b", "url": "http://x"}}], id_key="id")
assert [i["id"] for i in new] == ["2"]
out = format_items_as_markdown(new)
assert "## b" in out and "http://x" in out
print("OK")
"""
    r = subprocess.run([sys.executable, "-c", smoke], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_stocks_script_help_and_bad_range_dont_crash():
    script = ROOT / "stocks" / "scripts" / "stocks_client.py"
    r = _run(str(script), "--help")
    assert r.returncode == 0, r.stderr
    assert "quote" in r.stdout and "crypto" in r.stdout

    # history com range inválido não deve estourar exceção — imprime erro JSON e sai limpo (sem rede).
    r = _run(str(script), "history", "AAPL", "--range", "bogus")
    assert r.returncode != 0  # argparse rejeita choices inválido antes mesmo de chamar a rede


def test_pesquisa_web_scripts_run_without_crashing():
    scripts = ROOT / "pesquisa-web" / "scripts"

    r = _run(str(scripts / "search_arxiv.py"), "--help")
    assert r.returncode == 0 and "arxiv" in r.stdout.lower()

    r = _run(str(scripts / "search_arxiv.py"))  # sem args → imprime o help e sai limpo (0), sem traceback
    assert r.returncode == 0
    assert "traceback" not in r.stderr.lower()

    r = _run(str(scripts / "fetch_wikipedia.py"), "--help")
    assert r.returncode == 0 and "wikipedia" in r.stdout.lower()

    # --query é obrigatório (argparse) → sai com erro claro, sem traceback, sem tocar rede.
    r = _run(str(scripts / "fetch_wikipedia.py"))
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()


def test_github_skill_scripts_present_and_run_without_crashing():
    scripts_dir = ROOT / "github" / "scripts"
    names = {p.name for p in scripts_dir.glob("*.py")}
    assert {"_gh_auth.py", "gh_api.py"} <= names

    r = _run(str(scripts_dir / "gh_api.py"), "--help")
    assert r.returncode == 0 and "github" in r.stdout.lower()

    for sub in ("ci-status", "pr-list", "pr-merge", "issue-create", "issue-list",
                "issue-comment", "issue-close"):
        r = _run(str(scripts_dir / "gh_api.py"), sub, "--help")
        assert r.returncode == 0, r.stderr

    # _gh_auth lookup is pure (env/.env/.git-credentials) — no network, must never crash even
    # when none of those sources exist.
    smoke = f"""
import sys, os
sys.path.insert(0, {str(scripts_dir)!r})
os.environ.pop("GITHUB_TOKEN", None)
os.environ.pop("GH_TOKEN", None)
os.environ["OKAMI_HOME"] = "/tmp/okami-home-that-does-not-exist-xyz"
from _gh_auth import github_bearer
print(github_bearer())
print("OK")
"""
    r = subprocess.run([sys.executable, "-c", smoke], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
