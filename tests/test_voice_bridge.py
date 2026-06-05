"""Voice bridge: a LÓGICA do loop (STT→agente→TTS→play) com tudo injetado — sem hardware."""

from __future__ import annotations

from pathlib import Path

from okami.voice.bridge import VoiceBridge


def _bridge(tmp_path, *, transcript, reply="resposta do agente"):
    synth_calls, play_calls = [], []

    def synth(text, out):
        Path(out).write_text(text, encoding="utf-8")
        synth_calls.append(text)
        return out

    b = VoiceBridge(
        transcribe=lambda p: transcript,
        respond=lambda u: reply,
        synthesize=synth,
        play=lambda p: play_calls.append(p),
        workdir=tmp_path / "voice",
    )
    return b, synth_calls, play_calls


def test_full_turn_transcribes_responds_synthesizes_plays(tmp_path):
    b, synth, plays = _bridge(tmp_path, transcript="oi okami")
    user, reply, audio = b.handle_audio(tmp_path / "in.wav")
    assert user == "oi okami" and reply == "resposta do agente"
    assert audio is not None and audio.exists()
    assert synth == ["resposta do agente"] and len(plays) == 1     # sintetizou e tocou


def test_silence_is_a_noop(tmp_path):
    b, synth, plays = _bridge(tmp_path, transcript="   ")
    user, reply, audio = b.handle_audio(tmp_path / "in.wav")
    assert user == "" and reply == "" and audio is None
    assert synth == [] and plays == []                              # silêncio → não fala, não toca


def test_turn_without_recorder_raises(tmp_path):
    b, _, _ = _bridge(tmp_path, transcript="x")
    b.record = None
    try:
        b.turn()
        assert False, "deveria exigir um recorder"
    except RuntimeError as e:
        assert "mic" in str(e)


def test_loop_stops_on_silence(tmp_path):
    """O loop encerra no primeiro turno silencioso (sem mic real: record devolve um caminho fixo)."""
    seq = iter(["primeira fala", "   "])           # 2º turno = silêncio → para
    turns = []

    def _synth(t, o):
        Path(o).write_text(t, encoding="utf-8")
        return o

    b = VoiceBridge(
        transcribe=lambda p: next(seq),
        respond=lambda u: "ok",
        synthesize=_synth,
        record=lambda: tmp_path / "in.wav",
        workdir=tmp_path / "voice",
    )
    b.loop(on_turn=lambda u, r, a: turns.append(u))
    assert turns == ["primeira fala", ""]          # falou, depois silêncio → encerrou
