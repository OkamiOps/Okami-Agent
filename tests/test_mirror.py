"""Testes do espelho de entrega cross-sessão (okami.gateway.mirror).

Cobre o contrato PURO: mirror_record devolve (papel, texto) p/ gravar no transcript
da sessão-alvo, e should_mirror decide QUAIS origens viram espelho (entrega proativa
sim; fala do usuário não — senão duplicaria a própria mensagem do dono).
"""

from __future__ import annotations

from okami.gateway.mirror import mirror_record, should_mirror


def test_mirror_record_papel_e_texto_basico():
    # Entrega via cron → o agente do outro lado deve enxergar que ELE mandou isso.
    papel, texto = mirror_record("oi", source="cron")
    assert papel == "AGENTE"
    assert "cron" in texto          # marca a origem (sabe que foi entrega automática)
    assert "oi" in texto            # preserva o conteúdo original


def test_should_mirror_cron_true_user_false():
    assert should_mirror("cron") is True
    assert should_mirror("user") is False


def test_should_mirror_origens_de_entrega():
    # notify/send_message também são ENTREGA proativa do agente → espelham.
    assert should_mirror("notify") is True
    assert should_mirror("send_message") is True


def test_should_mirror_robusto_a_lixo():
    # Fail-safe: origem desconhecida/vazia/None não vira espelho, e nada explode.
    assert should_mirror("") is False
    assert should_mirror(None) is False  # type: ignore[arg-type]
    assert should_mirror("USER") is False  # case-insensitive p/ a fala do dono
    assert should_mirror(" Cron ") is True  # tolera espaço/maiúscula


def test_mirror_record_retorno_e_tupla_de_strs():
    out = mirror_record("relatório pronto", source="notify")
    assert isinstance(out, tuple) and len(out) == 2
    papel, texto = out
    assert isinstance(papel, str) and isinstance(texto, str)
    assert "relatório pronto" in texto


def test_mirror_record_default_source_cron():
    # source é keyword-only com default "cron".
    papel, texto = mirror_record("sem source explícito")
    assert papel == "AGENTE"
    assert "cron" in texto


def test_mirror_record_redige_segredo():
    # Se o texto carregar um segredo, o espelho NÃO o ecoa cru no transcript.
    papel, texto = mirror_record("token API_KEY=sk-ABCDEFGH12345678ZZ", source="cron")
    assert "sk-ABCDEFGH12345678ZZ" not in texto


def test_mirror_record_nunca_explode_com_lixo():
    # Best-effort: entrada não-str não derruba o caller.
    papel, texto = mirror_record(None, source="cron")  # type: ignore[arg-type]
    assert papel == "AGENTE"
    assert isinstance(texto, str)
