"""Tool store_secret — o agente RECEBE e GUARDA uma credencial sem se recusar nem ECOAR o valor.

Bug de produto: a Okami bloqueava TODO caminho de segredo (memória recusa, write_file/.shell barram
.env) e acabava se recusando a guardar uma API key/senha que o usuário mandou. store_secret é o
caminho SANCIONADO: grava no cofre (.env global, 0600), confirma só pelo NOME, NUNCA imprime o valor.
"""
from __future__ import annotations

import os

from okami.core.tools import ToolContext, default_registry
from okami.core.tools.secrets import StoreSecret


def _ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


def test_grava_no_env_global_com_0600(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    res = StoreSecret().run({"name": "ELEVENLABS_API_KEY", "value": "sk-abc123secretvalue"}, _ctx(tmp_path))
    assert res.ok and res.effect
    envf = tmp_path / ".env"
    assert envf.exists()
    assert "ELEVENLABS_API_KEY=sk-abc123secretvalue" in envf.read_text(encoding="utf-8")
    assert (envf.stat().st_mode & 0o777) == 0o600        # cofre só p/ o dono


def test_NAO_ecoa_o_valor_so_confirma_o_nome(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    res = StoreSecret().run({"name": "MINHA_SENHA", "value": "hunter2-supersegredo"}, _ctx(tmp_path))
    assert res.ok
    assert "hunter2-supersegredo" not in res.output      # o VALOR nunca aparece na saída
    assert "MINHA_SENHA" in res.output                    # confirma pelo NOME


def test_disponivel_no_processo_sem_reiniciar(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    try:
        StoreSecret().run({"name": "OKAMI_TEST_MIMO_KEY", "value": "xyz-immediate"}, _ctx(tmp_path))
        assert os.environ.get("OKAMI_TEST_MIMO_KEY") == "xyz-immediate"   # in-process já
    finally:
        os.environ.pop("OKAMI_TEST_MIMO_KEY", None)


def test_upsert_atualiza_nao_duplica(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    StoreSecret().run({"name": "TOKEN_X", "value": "v1"}, _ctx(tmp_path))
    StoreSecret().run({"name": "TOKEN_X", "value": "v2"}, _ctx(tmp_path))
    txt = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TOKEN_X=v2" in txt and "TOKEN_X=v1" not in txt
    assert txt.count("TOKEN_X=") == 1                     # uma linha só


def test_exige_name_e_value(tmp_path):
    assert StoreSecret().run({"value": "x"}, _ctx(tmp_path)).ok is False        # sem name
    assert StoreSecret().run({"name": "K"}, _ctx(tmp_path)).ok is False          # sem value
    assert StoreSecret().run({"name": "K", "value": ""}, _ctx(tmp_path)).ok is False   # value vazio


def test_normaliza_nome_para_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    res = StoreSecret().run({"name": "elevenlabs api key", "value": "v"}, _ctx(tmp_path))
    assert res.ok
    assert "ELEVENLABS_API_KEY=v" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_rejeita_quebra_de_linha_no_valor(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    res = StoreSecret().run({"name": "K", "value": "linha1\nFORJADO=mal"}, _ctx(tmp_path))
    assert res.ok is False                                # newline quebraria o formato .env → recusa


def test_registrada_no_default_registry():
    assert "store_secret" in default_registry()


def test_erro_nao_vaza_valor(monkeypatch, tmp_path):
    """Se a escrita falhar, a mensagem de erro NÃO pode conter o valor."""
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    import okami.config as cfg

    def _boom(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(cfg, "set_env_secret", _boom)
    res = StoreSecret().run({"name": "K", "value": "valor-secreto-do-erro"}, _ctx(tmp_path))
    assert res.ok is False
    assert "valor-secreto-do-erro" not in res.output


def test_tui_expanded_mascara_o_valor():
    """Defesa em profundidade: o /details expanded da TUI NÃO pode imprimir o valor do segredo."""
    from okami.tui import _args_full
    out = _args_full({"name": "ELEVENLABS_API_KEY", "value": "sk-naodeveaparecer"})
    assert "sk-naodeveaparecer" not in out
    assert "«oculto»" in out
    assert "ELEVENLABS_API_KEY" in out                    # o nome (não-sensível) ainda aparece
