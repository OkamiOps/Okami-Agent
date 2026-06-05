"""Testes do taste model de design (§9) — atrai/repele/explora + steering + persistência."""

from __future__ import annotations

from okami.learning.taste import TasteProfile, cosine, featurize, record_feedback


def test_featurize_and_cosine():
    a = featurize(["shadcn", "muted"], "airy spacing")
    b = featurize(["shadcn", "muted"], "airy spacing")
    c = featurize(["bootstrap", "neon"], "cluttered")
    assert cosine(a, b) > 0.999                                 # iguais (float)
    assert cosine(a, c) < 0.3                                   # bem diferentes


def test_approved_attracts_rejected_repels_in_score():
    p = TasteProfile()
    p.record("approved", ["shadcn", "muted", "airy"], "limpo e minimal")
    p.record("rejected", ["bootstrap", "neon"], "poluído")
    liked = p.score(["shadcn", "muted", "airy"], "limpo e minimal")
    disliked = p.score(["bootstrap", "neon"], "poluído")
    assert liked > 0 > disliked                                # atrai o curtido, repele o rejeitado


def test_want_different_is_mild_repulsor():
    p = TasteProfile()
    p.record("want_different", ["shadcn", "corporate"], "ok mas quero outro")
    assert p.repulsors and p.repulsors[0].weight == 0.5        # repulsão LEVE (não um 'odiei')
    assert p.score(["shadcn", "corporate"], "ok mas quero outro") < 0


def test_steer_text_lists_prefer_and_avoid():
    p = TasteProfile()
    p.record("approved", ["shadcn", "rounded"], "")
    p.record("rejected", ["bootstrap"], "")
    s = p.steer()
    assert "PREFIRA" in s and "shadcn" in s
    assert "EVITE" in s and "bootstrap" in s


def test_cold_start_asks_for_variety():
    s = TasteProfile().steer()
    assert "VARIEDADE" in s or "variedade" in s                # sem sinal → explora e pede feedback


def test_approve_decays_similar_repulsor():
    p = TasteProfile()
    p.record("rejected", ["shadcn", "muted", "airy"], "achei sem graça")
    p.record("approved", ["shadcn", "muted", "airy"], "mudei de ideia, gostei")
    # o repulsor parecido enfraquece (mudança de gosto), o atrator domina
    assert p.score(["shadcn", "muted", "airy"], "") > 0


def test_cap_prevents_unbounded_growth():
    p = TasteProfile()
    for i in range(40):
        p.record("approved", [f"estilo{i}"], "")
    assert len(p.attractors) <= 24                             # cap anti-overfitting/crescimento


def test_persistence_roundtrip(tmp_path):
    record_feedback(tmp_path, "like", "shadcn minimal", ["shadcn", "minimal"])
    prof2 = TasteProfile.load(tmp_path)
    assert len(prof2.attractors) == 1 and "shadcn" in prof2.attractors[0].tags
    assert prof2.score(["shadcn", "minimal"], "") > 0          # sobrevive ao reload


def test_record_feedback_verdict_aliases(tmp_path):
    record_feedback(tmp_path, "dislike", "bootstrap neon", promote=False)   # alias → rejected
    p = TasteProfile.load(tmp_path)
    assert len(p.repulsors) == 1 and p.repulsors[0].weight == 1.0


def test_promote_strong_taste_to_voice(tmp_path):
    # 'shadcn' curtido em 3 designs → vira preferência DURÁVEL no VOICE.md (taste→persona §8↔§9)
    for d in ("shadcn muted airy", "shadcn rounded", "shadcn minimal clean"):
        record_feedback(tmp_path, "like", d)
    voice = (tmp_path / "VOICE.md").read_text(encoding="utf-8")
    assert "shadcn" in voice and "design" in voice.lower()
    # não re-promove o mesmo termo
    record_feedback(tmp_path, "like", "shadcn extra")
    assert (tmp_path / "VOICE.md").read_text(encoding="utf-8").count("Em design, prefira 'shadcn'") == 1
