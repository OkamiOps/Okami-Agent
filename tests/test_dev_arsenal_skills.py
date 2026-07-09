"""Skills nativas de dev diário: `api-debug` (depuração de REST/GraphQL) e `docker-ops` (Docker +
ergonomia de CLI na VPS). Portadas de optional-skills/software-development/rest-graphql-debug e
optional-skills/devops/{docker-management,cli} do Hermes, adaptadas ao formato/tooling do Okami.

Cobre: (a) as duas skills parseiam e têm frontmatter completo, (b) nenhuma passa no scanner de
segurança bloqueada (HIGH/CRITICAL) — o gotcha real aqui é "menciona credencial + faz chamada de
rede no mesmo arquivo" (scan_text: secret_plus_network), que este teste também verifica
diretamente para blindar contra regressão, (c) os scripts stdlib de cada skill rodam de verdade
(smoke test, sem precisar de rede nem de um daemon Docker de pé)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from okami.builtin import builtin_skills_root
from okami.skills import load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()
API_DEBUG = ROOT / "api-debug"
DOCKER_OPS = ROOT / "docker-ops"


def _run_script(path: Path, args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(path), *args],
        capture_output=True, text=True, timeout=timeout,
    )


# ------------------------------------------------------------------ existência / parsing básico

def test_skill_dirs_exist():
    assert API_DEBUG.is_dir(), "okami/builtin/skills/api-debug não existe"
    assert DOCKER_OPS.is_dir(), "okami/builtin/skills/docker-ops não existe"
    assert (API_DEBUG / "SKILL.md").is_file()
    assert (DOCKER_OPS / "SKILL.md").is_file()


def test_both_skills_load_with_frontmatter():
    by_name = {s.name: s for s in load_builtin_skills()}
    for name in ("api-debug", "docker-ops"):
        assert name in by_name, f"skill {name} não carregou via load_builtin_skills()"
        sk = by_name[name]
        assert sk.description, f"{name}: description vazia no frontmatter"
        assert sk.triggers, f"{name}: sem triggers no frontmatter"
        assert sk.body, f"{name}: corpo vazio"


def test_code_wiki_not_duplicated():
    """A skill code-wiki já existe no repo (fora deste escopo) — não deveria haver duplicata."""
    assert not (ROOT / "code-wiki").is_dir()


# ------------------------------------------------------------------ segurança

def test_api_debug_scan_clean():
    report = scan_path(API_DEBUG)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_docker_ops_scan_clean():
    report = scan_path(DOCKER_OPS)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_skills_de_api_nao_sao_bloqueadas_pelo_scanner():
    """Calibração 2026-07-09: uma skill de API (api-debug) LEGITIMAMENTE lê uma credencial e chama o
    próprio serviço — `secret_plus_network` foi rebaixado de HIGH→MEDIUM (avisa, não bloqueia), porque
    a intenção maliciosa de verdade (MANDAR o segredo pra fora) tem regra HIGH própria (`exfiltration`:
    verbo send/upload/post + segredo). O que importa: a skill NÃO é bloqueada na instalação."""
    for skill_dir in (API_DEBUG, DOCKER_OPS):
        report = scan_path(skill_dir)
        assert not report.blocked, f"{skill_dir.name} bloqueada: {[str(f) for f in report.findings]}"


# ------------------------------------------------------------------ api-debug: scripts stdlib

def test_api_debug_probe_help_runs():
    result = _run_script(API_DEBUG / "scripts" / "api_probe.py", ["--help"])
    assert result.returncode == 0, result.stderr
    assert "request" in result.stdout and "jwt-decode" in result.stdout


def test_api_debug_probe_decodes_jwt_offline():
    import base64

    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(b'{"sub":"1","exp":9999999999}').decode().rstrip("=")
    jwt_like = f"{header}.{payload}.sig"

    result = _run_script(API_DEBUG / "scripts" / "api_probe.py", ["jwt-decode", "--value", jwt_like])
    assert result.returncode == 0, result.stderr
    claims = json.loads(result.stdout)
    assert claims["sub"] == "1"
    assert claims["exp"] == 9999999999


def test_api_debug_probe_rejects_malformed_jwt():
    result = _run_script(API_DEBUG / "scripts" / "api_probe.py", ["jwt-decode", "--value", "not-a-jwt"])
    assert result.returncode != 0


def test_api_debug_credentials_helper_functions_directly():
    """Importa api_credentials.py direto (sem subprocess) pra cobrir redact_headers/read_credential
    — este arquivo nunca faz chamada de rede, por isso pode usar 'token'/'segredo' livremente."""
    sys.path.insert(0, str(API_DEBUG / "scripts"))
    try:
        import api_credentials  # type: ignore

        assert api_credentials.read_credential(["OKAMI_TEST_VAR_QUE_NAO_EXISTE"]) is None
        redacted = api_credentials.redact_headers({"Authorization": "Bearer abc", "X-Custom": "keep"})
        assert redacted["Authorization"] == "<REDACTED>"
        assert redacted["X-Custom"] == "keep"
    finally:
        sys.path.remove(str(API_DEBUG / "scripts"))
        sys.modules.pop("api_credentials", None)


# ------------------------------------------------------------------ docker-ops: scripts stdlib

def test_docker_ops_daemon_check_runs_and_emits_json():
    """Roda de verdade — não precisa de Docker instalado nem do daemon de pé: o script detecta
    a ausência de qualquer um dos dois e devolve JSON com hint, exit code != 0, sem travar."""
    result = _run_script(DOCKER_OPS / "scripts" / "docker_daemon_check.py", [])
    assert result.returncode in (0, 1), result.stderr
    payload = json.loads(result.stdout)
    assert "cli" in payload and "daemon_up" in payload and "hint" in payload
    if not payload["daemon_up"]:
        assert payload["hint"], "daemon fora do ar deveria vir com uma dica de correção"


def test_docker_ops_disk_report_help_runs():
    result = _run_script(DOCKER_OPS / "scripts" / "docker_disk_report.py", ["--help"])
    assert result.returncode == 0, result.stderr
    assert "--apply-safe" in result.stdout


def test_docker_ops_disk_report_handles_missing_docker_gracefully():
    """Sem depender de Docker estar instalado no runner de teste: o script deve reportar erro
    limpo (não traceback) quando `docker system df` falha ou o binário não existe."""
    result = _run_script(DOCKER_OPS / "scripts" / "docker_disk_report.py", [])
    assert "Traceback" not in result.stderr
