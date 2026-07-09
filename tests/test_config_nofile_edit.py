"""Dono: ZERO edição de arquivo — chave de API de ferramenta e allowlist pelo menu, nunca vim na VPS."""
from unittest.mock import patch
import okami.cli.commands.config as c


def test_menu_tem_chave_e_allowlist():
    import inspect
    src = inspect.getsource(c.config_main)
    assert '"chave"' in src and '"allowlist"' in src


def test_setar_api_key_de_ferramenta_via_menu_grava_env():
    with patch("okami.menu._interactive", return_value=True), \
         patch("okami.menu.select", return_value="FIRECRAWL_API_KEY"), \
         patch("okami.menu.text", return_value="fc-abc123"), \
         patch.object(c, "config_set") as cs:
        c._manage_api_keys()
    cs.assert_called_once_with("FIRECRAWL_API_KEY", "fc-abc123")


def test_chave_outra_aceita_env_var_arbitraria():
    with patch("okami.menu._interactive", return_value=True), \
         patch("okami.menu.select", return_value="__other__"), \
         patch("okami.menu.text", side_effect=["mistral_api_key", "sk-xyz"]), \
         patch.object(c, "config_set") as cs:
        c._manage_api_keys()
    cs.assert_called_once_with("MISTRAL_API_KEY", "sk-xyz")   # normaliza p/ MAIÚSCULA


def test_allowlist_add_grava_local_yaml_sem_editar_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.config.config_dir", lambda: tmp_path)
    with patch("okami.menu._interactive", return_value=True), \
         patch("okami.menu.select", return_value="add"), \
         patch("okami.menu.text", return_value="987654321"), \
         patch("okami.cli._shared._write_local") as wl:
        c._manage_allowlist()
    upd = wl.call_args[0][0]
    assert upd["channels"]["telegram"]["allow_chats"] == ["987654321"]
    assert upd["channels"]["telegram"]["allow_all"] is False
