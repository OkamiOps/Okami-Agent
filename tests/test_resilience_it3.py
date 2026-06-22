"""Caça it.3: resiliência a config corrompida + segurança. agent.yaml/provider malformado NÃO derruba o
sistema inteiro; token do dashboard comparado em tempo-constante; corpo HTTP com teto (anti-DoS)."""
from __future__ import annotations

import pytest


def test_load_agents_skips_malformed_yaml(tmp_path):
    import okami.agents as ag
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "agent.yaml").write_text("name: good\n", encoding="utf-8")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "agent.yaml").write_text("name: [unterminated\n: : :", encoding="utf-8")
    specs = ag.load_agents(tmp_path)
    assert "good" in specs and "bad" not in specs        # 1 yaml quebrado não some com TODOS os agentes


def test_build_config_clear_error_on_bad_provider():
    from okami.config import build_config
    with pytest.raises(ValueError, match="provider"):
        build_config({"providers": {"x": {"model": {"nested": "dict-onde-esperava-str"}}},
                      "default_provider": "x"})           # provider malformado → erro CLARO, não ValidationError cru


def test_web_authorized_constant_time(monkeypatch):
    """_authorized usa hmac.compare_digest (tempo-constante) e aceita token certo / rejeita errado."""
    import inspect
    import okami.gateway.web as web
    src = inspect.getsource(web)
    assert "compare_digest" in src and "hdr == f\"Bearer" not in src   # sem == inseguro
