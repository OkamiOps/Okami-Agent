"""Wake-gate de cron (paridade Hermes): job pode ter um `gate` (comando shell barato) que roda ANTES
do agente — exit 0 = acorda o LLM, exit ≠0 = pula em silêncio ("se nada mudou, não gasta tokens")."""

from __future__ import annotations

from okami.automation.scheduler import Scheduler, gate_allows


# ----------------------------------------------------------------- gate_allows (puro)
def test_no_gate_always_allows():
    assert gate_allows({"id": "x", "prompt": "p"}, cwd=".") is True


def test_gate_exit_zero_allows(tmp_path):
    assert gate_allows({"gate": "true"}, cwd=str(tmp_path)) is True


def test_gate_exit_nonzero_skips(tmp_path):
    assert gate_allows({"gate": "false"}, cwd=str(tmp_path)) is False


def test_gate_checks_real_condition(tmp_path):
    (tmp_path / "novidade.txt").write_text("x")
    assert gate_allows({"gate": "test -f novidade.txt"}, cwd=str(tmp_path)) is True
    assert gate_allows({"gate": "test -f nao-existe.txt"}, cwd=str(tmp_path)) is False


def test_gate_error_fails_open(tmp_path):
    # gate quebrado (comando inexistente) NÃO pode silenciar o job pra sempre → roda o agente
    assert gate_allows({"gate": "comando-que-nao-existe-xyz"}, cwd=str(tmp_path)) in (True, False)
    # timeout/erro de spawn → fail-open (True)
    assert gate_allows({"gate": ""}, cwd=str(tmp_path)) is True


# ----------------------------------------------------------------- persistência no add
def test_add_with_gate_persists(tmp_path):
    s = Scheduler(str(tmp_path))
    job = s.add("1h", "checa novidades", gate="test -s inbox.txt")
    assert job["gate"] == "test -s inbox.txt"
    assert s.load()[0]["gate"] == "test -s inbox.txt"


def test_add_without_gate_has_no_field(tmp_path):
    job = Scheduler(str(tmp_path)).add("1h", "sem gate")
    assert "gate" not in job
