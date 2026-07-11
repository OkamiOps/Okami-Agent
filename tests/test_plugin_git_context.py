"""Plugin built-in git-context — injeta o estado do repo git (branch, ahead/behind, arquivos sujos) no
contexto de CADA turno via ctx.register_context (pre_llm_call). Testado (1) pelo CONTRATO de descoberta
(plugin_roots + discover_plugins acha o plugin nativo e o gateway consegue chamar o provider) e (2) pela
LÓGICA pura de parsing (sem precisar de um repo git de verdade em todo teste)."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO / "okami" / "builtin" / "plugins" / "git-context"


def _load_register_module():
    spec = importlib.util.spec_from_file_location("okami_plugin_git_context_test", PLUGIN_DIR / "register.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(path), check=True)
    (path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(path), check=True)


# ── descoberta: o plugin nativo aparece via plugin_roots() e contribui um provider real ──
def test_discovered_by_plugin_loader_and_registers_context_provider():
    from okami.plugins import discover_plugins, load_plugin_context, plugin_roots

    plugins = discover_plugins(plugin_roots())
    assert "git-context" in [p.name for p in plugins]
    provs = load_plugin_context(plugins)
    mine = [p for p in provs if p["plugin"] == "git-context"]
    assert len(mine) == 1
    assert mine[0]["name"] == "git-context"
    assert callable(mine[0]["fn"])


# ── efeito real: dentro de um repo git de verdade, o provider devolve branch + estado ──
def test_provider_reports_clean_branch(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKAMI_GITCONTEXT_DISABLE", raising=False)
    mod = _load_register_module()
    out = mod.git_context_provider()
    assert out.startswith("[git] branch main")
    assert "árvore limpa" in out


def test_provider_lists_dirty_files(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n")           # suja o arquivo rastreado
    (tmp_path / "b.py").write_text("y = 1\n")            # novo arquivo não rastreado
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKAMI_GITCONTEXT_DISABLE", raising=False)
    mod = _load_register_module()
    out = mod.git_context_provider()
    assert "2 arquivo(s) sujo(s)" in out
    assert "a.py" in out and "b.py" in out


def test_provider_respects_max_files_cap(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKAMI_GITCONTEXT_MAX_FILES", "2")
    mod = _load_register_module()
    out = mod.git_context_provider()
    assert "+8 mais" in out


# ── fail-safe: fora de repo git, plugin desligado, ou git ausente → string vazia (nunca derruba nada) ──
def test_provider_empty_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKAMI_GITCONTEXT_DISABLE", raising=False)
    mod = _load_register_module()
    assert mod.git_context_provider() == ""


def test_provider_empty_when_disabled(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKAMI_GITCONTEXT_DISABLE", "1")
    mod = _load_register_module()
    assert mod.git_context_provider() == ""


def test_run_git_status_swallows_missing_git(tmp_path, monkeypatch):
    mod = _load_register_module()
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert mod._run_git_status(str(tmp_path)) == ""


# ── injeção real no gateway: o provider entra no extra_context do turno ──
def test_inject_plugin_context_uses_git_context_provider(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    from okami.gateway.endpoint import _inject_plugin_context

    mod = _load_register_module()
    providers = [{"fn": mod.git_context_provider, "name": "git-context", "plugin": "git-context"}]
    out = _inject_plugin_context("histórico da conversa", providers)
    assert out.startswith("[git] branch main")
    assert "histórico da conversa" in out
