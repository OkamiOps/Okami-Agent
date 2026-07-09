"""Dono: menu de auth só mostrava codex; picker de modelo mostrava aliases, não os modelos reais.
Agora: TODOS os providers com credencial aparecem no auth (OAuth E api_key); picker lista provider→modelo real."""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import okami.cli.commands.config as c


def _cfg():
    cfg = MagicMock()
    codex = SimpleNamespace(auth="oauth_subscription", api_key_env=None, login_cmd=None, oauth=None,
                            tier="strong", models=["gpt-5.5"], model="gpt-5.5", ready=True)
    minimax = SimpleNamespace(auth="api_key", api_key_env="MINIMAX_API_KEY", login_cmd=None, oauth=None,
                              tier="weak", models=["MiniMax-M3", "MiniMax-M2.5"], model="MiniMax-M3", ready=True)
    lmstudio = SimpleNamespace(auth="api_key", api_key_env=None, key_env=None, login_cmd=None, oauth=None,
                               tier="local", models=["qwen"], model="qwen", ready=True, api_key="lm-studio")
    provs = {"codex": codex, "minimax": minimax, "lmstudio": lmstudio}
    cfg.providers = provs
    cfg.provider = lambda pid=None: provs.get(pid, codex)
    return cfg


def test_auth_state_api_key_provider_aparece():
    cfg = _cfg()
    with patch("okami.llm.oauth.codex_logged_in", return_value=True):
        m, k, ok = c._provider_auth_state(cfg, "minimax")
    assert m == "api_key" and k == "MINIMAX_API_KEY"     # minimax entra pelo caminho de API key


def test_auth_state_codex_oauth():
    cfg = _cfg()
    with patch("okami.llm.oauth.codex_logged_in", return_value=True):
        m, k, ok = c._provider_auth_state(cfg, "codex")
    assert m == "oauth" and ok is True


def test_auth_state_lmstudio_local_nao_exige_login():
    cfg = _cfg()
    m, k, ok = c._provider_auth_state(cfg, "lmstudio")
    assert m == "none"        # local sem credencial → fora do menu de auth


def test_picker_de_modelo_lista_modelos_reais():
    import okami.cli.commands.model as mod
    cfg = _cfg()
    with patch.object(mod, "_load", return_value=cfg), \
         patch.object(mod, "_effective", return_value=("minimax", "MiniMax-M3", "local")), \
         patch("okami.menu.select", return_value="codex/gpt-5.5") as sel, \
         patch("okami.llm.oauth.codex_logged_in", return_value=True), \
         patch.object(mod, "_apply") as ap:
        mod.model_cmd(token=None, save=True, as_json=False)
    rows = sel.call_args[0][1]
    tokens = {r[0] for r in rows}
    assert "codex/gpt-5.5" in tokens and "minimax/MiniMax-M3" in tokens and "minimax/MiniMax-M2.5" in tokens
    ap.assert_called_once_with(cfg, "codex/gpt-5.5", save=True)
