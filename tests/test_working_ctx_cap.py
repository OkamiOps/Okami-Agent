"""Teto de working-context (2026-07-08, uso real): num modelo de janela GIGANTE (minimax M3 = 1M tokens
setado explícito no config), a compaction NÃO pode esperar 0.72×1M ≈ 720K tokens pra disparar — arrastar
720K de contexto a cada passo é o que deixou gerar 1 PDF acumular 1.8M tok (lento/caro). O threshold é
capado num working-set são (~180K tok) INDEPENDENTE da janela; a janela segue sendo o limite duro."""
from okami.config import ProviderConfig
from okami.llm import providers as prov


def test_janela_gigante_ainda_compacta_em_working_set_sao():
    # janela explícita de 1M tokens (caso minimax M3) — o threshold NÃO pode ser 0.72×1M
    pc = ProviderConfig(name="big", model="whatever", context_window=1_000_000, chars_per_token=4.0)
    thr = prov.compaction_threshold_chars(pc)
    cap_chars = prov._WORKING_CTX_CAP_TOKENS * 4
    assert thr == cap_chars, f"threshold {thr} devia ser capado no working-set {cap_chars}"
    # ~180K tokens, MUITO abaixo dos ~720K de antes
    assert thr // 4 <= prov._WORKING_CTX_CAP_TOKENS
    assert thr < int(1_000_000 * 4 * prov.COMPACT_RATIO)   # menor que o proporcional-à-janela antigo


def test_janela_pequena_nao_e_afetada_pelo_cap():
    # modelo de janela pequena (128K): o proporcional-à-janela já é < cap → o cap não morde
    pc = ProviderConfig(name="small", model="whatever", context_window=128_000, chars_per_token=4.0)
    thr = prov.compaction_threshold_chars(pc)
    assert thr == int(128_000 * 4 * prov.COMPACT_RATIO)     # inalterado (menor que o cap)
    assert thr < prov._WORKING_CTX_CAP_TOKENS * 4
