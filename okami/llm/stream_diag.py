"""Diagnóstico de QUEDA de stream — porque "a resposta cortou" sozinho não diz nada acionável.

Quando um streaming de provider morre no meio, o erro que o caller vê costuma ser um
`RuntimeError`/`httpx.RemoteProtocolError` genérico envolvendo a causa real lá embaixo — e o
log fica com uma mensagem que não distingue os dois mundos opostos:

  - NÃO conectou (bytes_recv=0): handshake/TLS/rate-limit ANTES do primeiro byte → é problema de
    conexão/auth/capacidade; rotacionar chave ou trocar provider resolve.
  - MORREU streamando (já veio Nb/Mchunks): o provider começou a responder e largou no meio →
    é estabilidade/timeout do lado de lá; reconectar/retomar é o caminho, não trocar de chave.

Estas duas funções produzem UMA string curta e higienizada (segredo redigido) p/ log/erro:
- `flatten_exception_chain` achata `__cause__`/`__context__` em "Externo <- Interno <- Raiz".
- `format_drop` monta a linha do drop com ttfb/status/cf-ray/x-provider + a cadeia achatada.

Fail-safe por design: nunca levanta — é código de DIAGNÓSTICO; estourar aqui esconderia o erro
original que a gente está justamente tentando descrever.
"""

from __future__ import annotations

from okami.core.redact import redact

_MAX_ELOS = 8        # teto de elos andados (cadeia patológica/cíclica não vira parágrafo)
_MAX_MSG = 200       # cada mensagem de elo truncada — linha de log, não stack trace


def _msg_de(exc: BaseException) -> str:
    """'Tipo: mensagem' de um elo (só o tipo se a mensagem for vazia), truncado e sem quebra."""
    nome = type(exc).__name__
    try:
        texto = str(exc).strip()
    except Exception:
        texto = ""                                    # __str__ malcomportado não derruba o diag
    texto = " ".join(texto.split())                   # colapsa quebras/espaços → 1 linha
    if len(texto) > _MAX_MSG:
        texto = texto[: _MAX_MSG - 1] + "…"
    return f"{nome}: {texto}" if texto else nome


def flatten_exception_chain(exc) -> str:
    """Achata a cadeia de causas em "Externo <- Interno <- Raiz" andando __cause__/__context__.

    Dedup por id() (evita laço em cadeia cíclica e repetição quando __cause__ == __context__),
    teto de elos, e best-effort: entrada que não é exceção vira string inócua (nunca levanta)."""
    if not isinstance(exc, BaseException):
        return "" if exc is None else str(exc)        # lixo entra, lixo inócuo sai — sem estourar
    elos: list[str] = []
    vistos: set[int] = set()
    atual: BaseException | None = exc
    while atual is not None and len(elos) < _MAX_ELOS:
        if id(atual) in vistos:                       # cadeia cíclica: para
            break
        vistos.add(id(atual))
        elos.append(_msg_de(atual))
        # __cause__ (raise from) tem prioridade; senão o __context__ (exceção durante o handling)
        prox = atual.__cause__ or atual.__context__
        # não repete o MESMO elo (quando cause/context apontam pro mesmo objeto já visto)
        atual = prox if (prox is not None and id(prox) not in vistos) else None
    return " <- ".join(elos)


def _headers_uteis(headers) -> str:
    """Extrai SÓ os headers que ajudam a rastrear o drop (cf-ray, x-provider, x-request-id…).

    Case-insensitive; redige valor (header pode trazer token); best-effort p/ qualquer mapping."""
    if not headers:
        return ""
    try:
        itens = headers.items()
    except Exception:
        return ""
    alvo = ("cf-ray", "x-provider", "x-request-id", "x-amzn-requestid", "request-id")
    partes: list[str] = []
    for chave, valor in itens:
        try:
            nome = str(chave).lower()
        except Exception:
            continue
        if nome in alvo and valor not in (None, ""):
            partes.append(f"{nome}={redact(str(valor))}")
    return " ".join(partes)


def format_drop(*, ttfb=None, bytes_recv=0, chunks=0, status=None, headers=None, exc=None) -> str:
    """UMA linha higienizada descrevendo a queda de stream.

    Distingue "não conectou" (bytes_recv=0 — nenhum byte chegou) de "morreu streamando após Nb/Mchunks";
    anexa status HTTP, ttfb, headers de rastreio (cf-ray/x-provider) e a cadeia de exceção achatada.
    Fail-safe: qualquer parte que falhe é omitida, mas a função SEMPRE devolve uma string de 1 linha."""
    partes: list[str] = []
    try:
        try:
            recv = int(bytes_recv)
        except (TypeError, ValueError):
            recv = 0
        try:
            n_chunks = int(chunks)
        except (TypeError, ValueError):
            n_chunks = 0
        if recv <= 0:
            # nada chegou: foi ANTES do primeiro byte — conexão/auth/capacidade, não estabilidade de stream
            partes.append("stream não conectou (sem bytes recebidos)")
        else:
            partes.append(f"stream morreu streamando após {recv}b/{n_chunks}chunks")
        if status is not None:
            partes.append(f"status={status}")
        if ttfb is not None:
            try:
                partes.append(f"ttfb={float(ttfb):.3g}s")
            except (TypeError, ValueError):
                pass
        rastreio = _headers_uteis(headers)
        if rastreio:
            partes.append(rastreio)
        if exc is not None:
            cadeia = flatten_exception_chain(exc)
            if cadeia:
                partes.append(f"causa: {cadeia}")
    except Exception:
        # diagnóstico nunca derruba o caller — devolve o que deu p/ montar até aqui
        pass
    linha = redact(" | ".join(partes)) if partes else "queda de stream (sem detalhes)"
    return " ".join(linha.split())                    # garante 1 linha (sem \n vindo de mensagem de exc)
