"""ctx% e custo do rodapé/`/usage` usavam SEMPRE o provider DEFAULT (self.cfg.provider()), mesmo quando
a sessão respondeu por outro provider (/model <provider> troca s.provider_override por turno, sem tocar
cfg.default_provider) — janela de contexto errada (ex.: mostrava % contra os 32K do local quando quem
serviu foi o minimax de 1M). `_served_provider` resolve pelo `served_by` real do turno (§E5), com
fallback pro override da sessão e só por último o default."""
from __future__ import annotations

from okami.config import build_config
from okami.gateway.endpoint import AgentEndpoint


def _cfg():
    return build_config({
        "default_provider": "lmstudio",
        "providers": {
            "lmstudio": {"model": "m", "context_window": 32768, "transport": "litellm"},
            "minimax": {"model": "openai/MiniMax-M3", "context_window": 1_000_000, "transport": "litellm"},
        },
    })


def _ep(cfg):
    ep = AgentEndpoint.__new__(AgentEndpoint)
    ep.cfg = cfg
    return ep


def test_served_provider_prefers_served_by_over_default():
    ep = _ep(_cfg())
    s = type("S", (), {"provider_override": ""})()
    pc = ep._served_provider(s, {"served_by": "minimax/openai/MiniMax-M3"})
    assert pc.model == "openai/MiniMax-M3"


def test_served_provider_falls_back_to_session_override():
    ep = _ep(_cfg())
    s = type("S", (), {"provider_override": "minimax"})()
    pc = ep._served_provider(s, {})            # sem served_by ainda (1o turno) → usa override da sessão
    assert pc.model == "openai/MiniMax-M3"


def test_served_provider_falls_back_to_cfg_default():
    ep = _ep(_cfg())
    s = type("S", (), {"provider_override": ""})()
    pc = ep._served_provider(s, {})
    assert pc.model == "m"


def test_turn_footer_ctx_pct_uses_served_provider_not_default():
    """Sessão default=lmstudio (32K) mas o turno foi servido pelo minimax (1M) — ctx% deve refletir a
    janela de QUEM RESPONDEU, senão 15.6K tokens contra 32K mostraria ~48% em vez dos ~2% reais."""
    ep = _ep(_cfg())
    s = type("S", (), {"provider_override": ""})()
    stats = {"usage": {"input": 15500, "output": 36, "cache_read": 114}, "served_by": "minimax/openai/MiniMax-M3"}
    out = ep._turn_footer(s, stats, 3.7)
    assert "ctx 2%" in out            # 15650/1_000_000 ≈ 2% (não ~48% do lmstudio)


def test_usage_text_prices_by_served_provider_not_default():
    """`/usage` (endpoint_commands._usage_text) usava sempre self.cfg.provider() (default=lmstudio, sem
    entrada em _PRICING → 'unknown'/'—') mesmo quando a sessão inteira rodou no minimax — custo saía
    sempre '—' em vez do preço real do provider que respondeu."""
    ep = _ep(_cfg())
    ep.session = lambda cid: type("S", (), {"provider_override": ""})()
    entry = {"usage": {"input": 1_000_000, "output": 0}, "served_by": "minimax/openai/MiniMax-M3"}
    ep.store = type("St", (), {"entry": lambda self, cid: entry})()
    out = ep._usage_text("c1")
    assert "0.3000" in out or "$0.30" in out    # 1M tokens de input a $0.30/1M do minimax — não '—'
