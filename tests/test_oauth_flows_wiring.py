"""Costura dos fluxos OAuth (paridade Hermes): registry único + presets + dispatch no login/transport."""
from okami.llm import oauth_flows
from okami.provider_catalog import PRESETS
from okami.config import ProviderConfig

_FLOW_PRESETS = {"minimax-oauth": "minimax_oauth", "xai-oauth": "xai_oauth",
                 "claude-oauth": "anthropic_pkce", "nous": "nous_device",
                 "qwen-oauth": "qwen_cli", "copilot": "copilot_device"}


def test_todos_os_fluxos_conhecidos_resolvem():
    known = set(oauth_flows.known_flows())
    for flow in _FLOW_PRESETS.values():
        assert flow in known, f"fluxo {flow} não registrado"
        assert oauth_flows.has_flow(flow)


def test_token_for_fluxo_desconhecido_e_none():
    assert oauth_flows.token_for("inexistente") is None


def test_presets_oauth_constroem_com_auth_flow():
    by_key = {p.key: p for p in PRESETS}
    for key, flow in _FLOW_PRESETS.items():
        assert key in by_key, f"preset {key} sumiu do catálogo"
        pc = ProviderConfig(name=key, **by_key[key].base)     # build real (armadilha config-drop)
        assert pc.auth_flow == flow, f"{key}: auth_flow não persistiu no build"


def test_minimax_oauth_endpoint_e_anthropic_nao_v1():
    # bug do preset antigo: inferência ia em /v1 (OpenAI-compat); o correto é /anthropic
    by_key = {p.key: p for p in PRESETS}
    assert by_key["minimax-oauth"].base["api_base"].endswith("/anthropic")


def test_qwen_flow_sem_login_proprio_emite_dica(capsys=None):
    msgs = []
    out = oauth_flows.run_login("qwen_cli", msgs.append)
    assert out is None
    assert any("qwen" in m.lower() for m in msgs)
