"""Diretório de canais por apelido (paridade Hermes: resolver "família" → "-100123" no envio remoto).
Persistido em JSON com escrita atômica (tmp + os.replace) — sobrevive entre instâncias no mesmo path.
resolve() casa por apelido OU por match exato do target (idempotência: alvo cru já resolvido passa)."""

from __future__ import annotations

import json

from okami.gateway.channel_directory import ChannelDirectory


def test_add_resolve_persiste_entre_instancias(tmp_path):
    p = tmp_path / "channels.json"
    d = ChannelDirectory(p)
    d.add_alias("família", "-100123")
    # Nova instância no MESMO path: lê do disco, não da memória.
    d2 = ChannelDirectory(p)
    assert d2.resolve("família") == "-100123"


def test_resolve_desconhecido_e_none(tmp_path):
    d = ChannelDirectory(tmp_path / "channels.json")
    assert d.resolve("desconhecido") is None


def test_resolve_por_target_exato(tmp_path):
    # Idempotência: passar o TARGET cru (já resolvido) também resolve p/ ele mesmo.
    d = ChannelDirectory(tmp_path / "channels.json")
    d.add_alias("família", "-100123")
    assert d.resolve("-100123") == "-100123"


def test_all_tem_a_entrada(tmp_path):
    d = ChannelDirectory(tmp_path / "channels.json")
    d.add_alias("família", "-100123")
    mapa = d.all()
    assert mapa == {"família": "-100123"}
    # all() devolve cópia: mutar o retorno NÃO contamina o estado interno.
    mapa["x"] = "y"
    assert "x" not in d.all()


def test_remove_alias(tmp_path):
    p = tmp_path / "channels.json"
    d = ChannelDirectory(p)
    d.add_alias("família", "-100123")
    assert d.remove_alias("família") is True
    assert d.resolve("família") is None
    assert d.remove_alias("família") is False        # já não existe → False, sem exceção
    # Removeu de verdade no disco: nova instância também não acha.
    assert ChannelDirectory(p).resolve("família") is None


def test_escrita_atomica_sem_tmp_orfao(tmp_path):
    p = tmp_path / "channels.json"
    d = ChannelDirectory(p)
    d.add_alias("a", "1")
    # JSON válido no destino e nenhum .tmp deixado pra trás.
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": "1"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_path_corrompido_nao_derruba(tmp_path):
    # Fail-safe: arquivo lixo no path → trata como vazio, não levanta no caller.
    p = tmp_path / "channels.json"
    p.write_text("{lixo não-json", encoding="utf-8")
    d = ChannelDirectory(p)
    assert d.all() == {}
    assert d.resolve("família") is None
    d.add_alias("família", "-100123")               # e ainda dá pra gravar por cima
    assert ChannelDirectory(p).resolve("família") == "-100123"
