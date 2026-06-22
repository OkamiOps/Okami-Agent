"""check() de disponibilidade nas tools de integração (caça field-fail): generate_video/homeassistant/
feishu_doc_read/x_search NÃO podavam quando a integração não estava configurada → o agente as via, chamava
e levava um erro feio em runtime. Agora check() devolve um motivo claro e a tool some do registro quando
a integração falta — igual a computer_use/web_search. (vision/web_extract NÃO entram: caem no modelo
principal via aux_complete, então funcionam sem config — podá-las seria remover tool que funciona.)"""
from __future__ import annotations

import importlib

import pytest

# (módulo da tool, classe, módulo do helper de config, nome do helper)
CASES = [
    ("okami.core.tools.video", "GenerateVideo", "okami.llm.videogen", "video_config"),
    ("okami.core.tools.homeassistant", "HomeAssistant", "okami.integrations.homeassistant", "ha_config"),
    ("okami.core.tools.feishu", "FeishuDocRead", "okami.integrations.feishu", "feishu_config"),
    ("okami.core.tools.x_search", "XSearch", "okami.integrations.x_search", "x_config"),
]


@pytest.mark.parametrize("tmod,cls,cmod,cfn", CASES, ids=[c[1] for c in CASES])
def test_check_prunes_when_unconfigured(tmod, cls, cmod, cfn, monkeypatch):
    import okami.config as okcfg
    monkeypatch.setattr(okcfg, "load_config", lambda: {})        # config determinística
    tool = getattr(importlib.import_module(tmod), cls)()
    cfgmod = importlib.import_module(cmod)
    monkeypatch.setattr(cfgmod, cfn, lambda cfg: None)           # integração AUSENTE
    reason = tool.check()
    assert reason and isinstance(reason, str)                    # poda com motivo claro
    monkeypatch.setattr(cfgmod, cfn, lambda cfg: {"ok": 1})      # integração PRESENTE
    assert tool.check() is None                                  # disponível


def test_check_failopen_when_config_unreadable(monkeypatch):
    """Erro ao ler config NÃO pode podar a tool (fail-open do check) — senão um glitch some com a tool."""
    import okami.config as okcfg

    def boom():
        raise RuntimeError("config ilegível")
    monkeypatch.setattr(okcfg, "load_config", boom)
    from okami.core.tools.x_search import XSearch
    assert XSearch().check() is None                             # não poda por erro de leitura


def test_unconfigured_integration_tools_pruned_from_registry(monkeypatch):
    """Fim-a-fim: sem nenhuma integração configurada, as 4 tools somem do registro (não ficam visíveis
    pro agente chamar e quebrar)."""
    import okami.config as okcfg
    import okami.integrations.feishu as fe
    import okami.integrations.homeassistant as ha
    import okami.integrations.x_search as xs
    import okami.llm.videogen as vg
    monkeypatch.setattr(okcfg, "load_config", lambda: {})
    monkeypatch.setattr(vg, "video_config", lambda cfg: None)
    monkeypatch.setattr(ha, "ha_config", lambda cfg: None)
    monkeypatch.setattr(fe, "feishu_config", lambda cfg: None)
    monkeypatch.setattr(xs, "x_config", lambda cfg: None)
    from okami.core.tool_policy import prune_unavailable
    from okami.core.tools.registry import default_registry
    out = prune_unavailable(default_registry(), emit=lambda m: None)
    for name in ("generate_video", "homeassistant", "feishu_doc_read", "x_search"):
        assert name not in out
