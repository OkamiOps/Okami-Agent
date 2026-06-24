"""Paridade Hermes (UX): batch-delay ADAPTATIVO no streaming-by-edit. Conteúdo CURTO edita mais rápido
(resposta parece snappy); LONGO mantém o throttle cheio (eficiência/anti-429). A 1ª edição sempre sai na
hora; o adaptativo só acelera as edições SEGUINTES de conteúdo curto, nunca passa do min_interval (cap)."""
from __future__ import annotations

from okami.gateway.streamedit import StreamEditor


def test_first_edit_always_immediate():
    ed = StreamEditor(min_interval=1.2)
    ed.feed("x" * 2000, 0.0)
    assert ed.due(0.0) is True                   # 1ª edição não espera (last_sent=-inf)


def test_short_content_flushes_faster_than_full_interval():
    ed = StreamEditor(min_interval=1.2)
    ed.feed("linha curta", 0.0)                   # ≤320 → intervalo curto (0.5s)
    ed.mark_sent(0.0)
    assert ed.due(0.3) is False
    assert ed.due(0.6) is True


def test_medium_content_intermediate_interval():
    ed = StreamEditor(min_interval=1.2)
    ed.feed("x" * 500, 0.0)                       # ≤1024 → 0.8s
    ed.mark_sent(0.0)
    assert ed.due(0.5) is False
    assert ed.due(0.9) is True


def test_long_content_keeps_full_throttle():
    ed = StreamEditor(min_interval=1.2)
    ed.feed("x" * 1100, 0.0)                      # >1024 → intervalo cheio (anti-429)
    ed.mark_sent(0.0)
    assert ed.due(0.6) is False
    assert ed.due(1.3) is True


def test_adaptive_off_uses_fixed_interval():
    ed = StreamEditor(min_interval=1.2, adaptive=False)
    ed.feed("curta", 0.0)
    ed.mark_sent(0.0)
    assert ed.due(0.6) is False                   # desligado → fixo mesmo p/ conteúdo curto
    assert ed.due(1.3) is True


def test_adaptive_never_exceeds_cap():
    ed = StreamEditor(min_interval=0.3)           # cap baixo: curto não pode ficar MAIS lento que o cap
    ed.feed("curta", 0.0)
    ed.mark_sent(0.0)
    assert ed.due(0.35) is True


def test_streaming_size_param_drives_interval():
    """Regressão: o caminho de streaming token-a-token tem o texto FORA do deque → due(now, size) precisa
    usar o size, senão trava no piso 0.5s e mata o teto anti-429."""
    ed = StreamEditor(min_interval=1.2)                 # _lines vazio (stream não usa feed)
    ed.mark_sent(0.0)
    assert ed.due(0.6, size=2000) is False             # buffer grande → teto cheio 1.2s (NÃO 0.5)
    assert ed.due(1.3, size=2000) is True
    assert ed.due(0.6, size=100) is True               # buffer pequeno → 0.5s (snappy)
