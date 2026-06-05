"""Persona Compiler contextual (#8) — direção CURTA do turno (read-only)."""

from __future__ import annotations

from okami.learning.compiler import compile_turn


def test_casual_but_technical_pulls_precision():
    out = compile_turn("amor, como faço esse deploy do docker parar de quebrar?")
    assert "técnico" in out and "precisão" in out.lower()


def test_pure_casual_emits_nothing():
    assert compile_turn("oi amor, tudo bem? tava com saudade") == ""   # sem sinal → não infla o prompt


def test_work_mode_without_emotion_is_empty():
    # modo trabalho (critério verificável) → o prompt estático já endurece; sem emoção, bloco vazio
    out = compile_turn("cria o componente de login", exit_criteria=[{"type": "file_exists", "path": "x"}])
    assert out == ""


def test_frustration_detected_and_openness_rule():
    out = compile_turn("isso nao funciona de novo, que saco")
    assert "frustrada" in out.lower() and "ABERTURA" in out and "não a solução" in out


def test_urgency_detected():
    out = compile_turn("urgente, preciso disso pra ontem")
    assert "pressa" in out.lower()


def test_excitement_detected():
    out = compile_turn("amei, ficou incrivel, top demais!")
    assert "animada" in out.lower()


def test_block_is_marked_internal():
    out = compile_turn("o git merge deu erro de novo, que saco")
    assert out.startswith("NESTE TURNO") and "não recite" in out
