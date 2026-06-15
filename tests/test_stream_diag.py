"""stream_diag: diagnóstico de queda de stream — cadeia de exceções + 1 linha de drop."""

from __future__ import annotations

from okami.llm.stream_diag import flatten_exception_chain, format_drop


def _nested_chain():
    """Monta uma cadeia de 3 exceções aninhadas (raiz -> meio -> topo) via `raise from`."""
    try:
        try:
            try:
                raise ValueError("erro raiz")
            except ValueError as raiz:
                raise ConnectionError("camada do meio") from raiz
        except ConnectionError as meio:
            raise RuntimeError("erro externo") from meio
    except RuntimeError as topo:
        return topo


def test_flatten_chain_de_tres_em_ordem():
    s = flatten_exception_chain(_nested_chain())
    # as 3 mensagens aparecem, e o EXTERNO vem antes da RAIZ
    assert "erro externo" in s and "camada do meio" in s and "erro raiz" in s
    assert s.index("erro externo") < s.index("camada do meio") < s.index("erro raiz")


def test_flatten_inclui_tipo_e_dedup():
    s = flatten_exception_chain(_nested_chain())
    # mostra o tipo de cada elo
    assert "RuntimeError" in s and "ConnectionError" in s and "ValueError" in s
    # exceção solta: 1 elo só, sem seta
    assert "<-" not in flatten_exception_chain(ValueError("sozinha"))


def test_flatten_failsafe_para_lixo():
    # nunca levanta: entrada não-exceção/None vira string vazia/inócua
    assert isinstance(flatten_exception_chain(None), str)
    assert isinstance(flatten_exception_chain("nem é exceção"), str)


def test_format_drop_nao_conectou_sem_bytes():
    linha = format_drop(bytes_recv=0, chunks=0, status=503)
    low = linha.lower()
    assert ("não conectou" in low) or ("nao conectou" in low) or ("sem bytes" in low)
    assert "503" in linha
    assert "\n" not in linha  # 1 linha só


def test_format_drop_morreu_streamando_menciona_bytes():
    linha = format_drop(bytes_recv=2048, chunks=5, ttfb=0.3)
    assert "2048" in linha           # os bytes recebidos
    assert "5" in linha              # os chunks
    assert "0.3" in linha            # ttfb
    low = linha.lower()
    assert "stream" in low           # distingue de "não conectou"
    assert "\n" not in linha


def test_format_drop_inclui_headers_uteis():
    linha = format_drop(
        bytes_recv=10, chunks=1,
        headers={"cf-ray": "abc123-GRU", "x-provider": "anthropic", "x-irrelevante": "x"},
        status=502,
    )
    assert "abc123-GRU" in linha and "anthropic" in linha
    assert "\n" not in linha


def test_format_drop_anexa_cadeia_de_excecao():
    linha = format_drop(bytes_recv=0, exc=_nested_chain())
    assert "erro externo" in linha and "erro raiz" in linha
    assert "\n" not in linha


def test_format_drop_redige_segredo_em_header_e_exc():
    linha = format_drop(
        bytes_recv=0,
        headers={"x-provider": "Bearer abcdef1234567890"},
        exc=RuntimeError("falhou com token=sk-ABCDEFGHIJKLMNOP1234"),  # pragma: allowlist secret
    )
    assert "abcdef1234567890" not in linha
    assert "sk-ABCDEFGHIJKLMNOP1234" not in linha  # pragma: allowlist secret


def test_format_drop_failsafe_sem_nada():
    # sem argumento nenhum: ainda devolve 1 string, sem estourar
    linha = format_drop()
    assert isinstance(linha, str) and "\n" not in linha
