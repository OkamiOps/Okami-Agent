"""Falhas SILENCIOSAS de memória (sweep #1/#2/#3): tools de memória fingiam sucesso quando a escrita/staging
falhava — o dono achava que algo foi salvo e nunca foi. Agora sinalizam falha de verdade (ToolResult.ok=False)."""
from __future__ import annotations

from pathlib import Path

from okami.core.tools.memory import FinishSetup, RememberFact, RememberUser

_FAKE_SECRET = "AKIA" + "IOSFODNN7EXAMPLE"          # fake (concatenado) — looks_secret pega


class _Ctx:
    """ToolContext mínimo p/ as tools de memória."""
    def __init__(self, home, *, stage_writes=False):
        self.home = Path(home)
        self.memory = None
        self.stage_writes = stage_writes


# ----------------------------------------------------------------- #3 recusa por segredo NÃO é "sucesso"
def test_remember_user_secret_returns_failure(tmp_path):
    r = RememberUser().run({"text": f"minha chave é {_FAKE_SECRET}"}, _Ctx(tmp_path))
    assert r.ok is False                                # antes era True (enganava o modelo)
    assert not (tmp_path / "USER.md").exists() or _FAKE_SECRET not in (tmp_path / "USER.md").read_text()


# ----------------------------------------------------------------- #2 FinishSetup não esconde falha do USER.md
def test_finish_setup_surfaces_user_write_failure(tmp_path):
    r = FinishSetup().run({"about_user": f"token {_FAKE_SECRET}"}, _Ctx(tmp_path))
    assert (tmp_path / ".okami" / "genesis.done").exists()   # gênese conclui (não trava por causa do USER.md)
    assert "USER.md" in r.output or "não consegui" in r.output.lower()   # MAS avisa que a nota não entrou


# ----------------------------------------------------------------- #1 stage() que falha NÃO finge "staged"
def test_remember_fact_stage_failure_is_reported(tmp_path, monkeypatch):
    from okami.memory import staging
    def boom(self, *a, **k):
        raise PermissionError("disco cheio")
    monkeypatch.setattr(staging.PendingStore, "stage", boom)
    r = RememberFact().run({"text": "um fato durável importante sobre o projeto"},
                           _Ctx(tmp_path, stage_writes=True))
    assert r.ok is False                                # antes: exceção crua / "staged" mentiroso
    assert "enfileirar" in r.output.lower() or "aprovaç" in r.output.lower()
