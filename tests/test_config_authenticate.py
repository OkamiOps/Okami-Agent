"""Menu okami config → autenticar provider (login), pedido do dono: abrir providers e autenticar
sem editar .env. Reusa okami.cli.commands.basics.login (device-flow/CLI)."""
from unittest.mock import patch, MagicMock
import okami.cli.commands.config as c


def test_menu_lista_opcao_autenticar():
    import inspect
    src = inspect.getsource(c.config_main)
    assert '"autenticar"' in src or "'autenticar'" in src


def test_authenticate_chama_login_no_escolhido():
    cfg = MagicMock()
    cfg.providers = {"codex": {}}
    pc = MagicMock(); pc.login_cmd = None; pc.oauth = None
    cfg.provider = lambda pid=None: pc
    with patch.object(c, "_load", return_value=cfg), \
         patch("okami.menu._interactive", return_value=True), \
         patch("okami.menu.select", return_value="codex"), \
         patch("okami.cli.commands.basics.login") as mock_login, \
         patch("okami.llm.oauth.codex_logged_in", return_value=True):
        c._authenticate_provider()
    mock_login.assert_called_once_with("codex")


def test_authenticate_sem_tty_degrada_sem_chamar_login():
    cfg = MagicMock(); cfg.providers = {"codex": {}}
    pc = MagicMock(); pc.login_cmd = None; pc.oauth = None
    cfg.provider = lambda pid=None: pc
    with patch.object(c, "_load", return_value=cfg), \
         patch("okami.menu._interactive", return_value=False), \
         patch("okami.cli.commands.basics.login") as mock_login, \
         patch("okami.llm.oauth.codex_logged_in", return_value=False):
        c._authenticate_provider()
    mock_login.assert_not_called()
