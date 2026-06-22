"""Provisão remota (VPS-first): o agente bootstrappa o PRÓPRIO acesso SSH/GitHub sem depender da máquina
do dono. Caminho sancionado que escreve em ~/.ssh + configura git auth (file-based → sobrevive ao env
sanitizado). Segredo nunca volta no retorno. Usa ssh-keygen/git REAIS com HOME=tmp_path (offline, isolado)."""
from __future__ import annotations

import pytest

from okami.integrations import provision as pr


def test_generate_ssh_key_idempotent(tmp_path):
    r1 = pr.generate_ssh_key(home=tmp_path)
    assert r1["created"] and r1["public_key"].startswith("ssh-ed25519")
    priv = tmp_path / ".ssh" / "id_ed25519"
    assert priv.exists() and oct(priv.stat().st_mode)[-3:] == "600"      # privada 0600
    r2 = pr.generate_ssh_key(home=tmp_path)
    assert not r2["created"] and r2["public_key"] == r1["public_key"]    # não sobrescreve


def test_import_private_key_derives_public(tmp_path_factory):
    src = tmp_path_factory.mktemp("src")
    pr.generate_ssh_key(home=src)
    material = (src / ".ssh" / "id_ed25519").read_text(encoding="utf-8")
    dst = tmp_path_factory.mktemp("dst")
    r = pr.import_private_key(material, home=dst)
    assert r["imported"] and r["public_key"].startswith("ssh-ed25519")   # derivou a .pub da privada
    assert oct((dst / ".ssh" / "id_ed25519").stat().st_mode)[-3:] == "600"


def test_configure_git_token_is_file_based(tmp_path):
    secret = "ghp_" + "FILEBASEDTOKEN1234567890"
    r = pr.configure_git_token(secret, user_name="Okami", user_email="a@b.c", home=tmp_path)
    cred = tmp_path / ".git-credentials"
    assert cred.is_file() and oct(cred.stat().st_mode)[-3:] == "600"
    body = cred.read_text(encoding="utf-8")
    assert "x-access-token:" in body and "@github.com" in body
    gc = (tmp_path / ".gitconfig").read_text(encoding="utf-8")           # git config caiu no HOME injetado
    assert "credential" in gc.lower() and "Okami" in gc
    assert secret not in str(r)                                          # retorno NUNCA carrega o segredo


def test_configure_git_token_replaces_same_host(tmp_path):
    pr.configure_git_token("ghp_" + "TOKENONE111", home=tmp_path)
    pr.configure_git_token("ghp_" + "TOKENTWO222", home=tmp_path)
    lines = [ln for ln in (tmp_path / ".git-credentials").read_text(encoding="utf-8").splitlines()
             if "github.com" in ln]
    assert len(lines) == 1 and "TOKENTWO222" in lines[0]                 # substitui, não duplica


def test_known_host_appends_and_dedupes(tmp_path):
    def fake(argv, **kw):
        return (0, "github.com ssh-ed25519 AAAAFAKEKEYDATA\n")
    assert pr.known_host("github.com", home=tmp_path, run_fn=fake)["added"]
    assert not pr.known_host("github.com", home=tmp_path, run_fn=fake)["added"]   # dedupe
    kh = (tmp_path / ".ssh" / "known_hosts").read_text(encoding="utf-8")
    assert kh.count("github.com ssh-ed25519 AAAAFAKEKEYDATA") == 1


def test_git_auth_status_reports_without_secret(tmp_path):
    secret = "ghp_" + "STATUSSECRET777"
    pr.configure_git_token(secret, user_name="Okami", home=tmp_path)
    pr.generate_ssh_key(home=tmp_path)
    st = pr.git_auth_status(home=tmp_path)
    assert "github.com" in st["token_hosts"]
    assert st["ssh_keys"] and st["ssh_keys"][0]["name"] == "id_ed25519"
    assert secret not in str(st)                                         # estado sem revelar segredo


def test_verify_parses_github_success(tmp_path):
    def fake(argv, **kw):
        return (1, "Hi marcos! You've successfully authenticated, but GitHub does not provide shell access.")
    assert pr.verify(home=tmp_path, run_fn=fake)["ssh_ok"] is True       # exit 1 do GitHub = sucesso


def test_rejects_traversal_name_and_injection_host(tmp_path):
    with pytest.raises(ValueError):
        pr.generate_ssh_key(name="../evil", home=tmp_path)              # sem traversal no nome da chave
    with pytest.raises(ValueError):
        pr.known_host("-oProxyCommand=evil", home=tmp_path)            # host '-' viraria flag ssh


# ── as TOOLS (ssh_identity / git_auth) que o agente chama — approval-gated, sem vazar segredo ──
def _ctx(tmp_path):
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=tmp_path)


def test_ssh_identity_generate_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_PROVISION_HOME", str(tmp_path))
    from okami.core.tools.provision import SshIdentity
    res = SshIdentity().run({"action": "generate"}, _ctx(tmp_path))
    assert res.ok and "ssh-ed25519" in res.output                # mostra a PÚBLICA p/ colar no GitHub
    assert (tmp_path / ".ssh" / "id_ed25519").exists()


def test_ssh_identity_import_requires_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_PROVISION_HOME", str(tmp_path))
    from okami.core.tools.provision import SshIdentity
    res = SshIdentity().run({"action": "import"}, _ctx(tmp_path))
    assert not res.ok and "private_key" in res.output


def test_git_auth_token_from_stored_secret_no_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_PROVISION_HOME", str(tmp_path))
    secret = "ghp_" + "TOOLTOKEN1234567890"
    monkeypatch.setenv("GITHUB_TOKEN", secret)                   # como se store_secret tivesse guardado
    from okami.core.tools.provision import GitAuth
    res = GitAuth().run({"action": "token", "secret": "GITHUB_TOKEN", "user_name": "Okami"}, _ctx(tmp_path))
    assert res.ok and secret not in res.output                  # configurou e NÃO vazou o token
    assert (tmp_path / ".git-credentials").is_file()


def test_git_auth_token_missing_errs(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_PROVISION_HOME", str(tmp_path))
    from okami.core.tools.provision import GitAuth
    res = GitAuth().run({"action": "token"}, _ctx(tmp_path))
    assert not res.ok


def test_provision_tools_registered_and_dangerous():
    from okami.core.tool_registry import TOOL_REGISTRY
    from okami.core.tools.registry import default_registry
    reg = default_registry()
    assert "ssh_identity" in reg and "git_auth" in reg
    specs = {s.name: s for s in TOOL_REGISTRY}
    assert specs["ssh_identity"].danger == "dangerous"          # approval-gated + negado no Telegram sem grant
    assert specs["git_auth"].danger == "dangerous"
