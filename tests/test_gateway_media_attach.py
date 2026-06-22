"""Entrega de mídia GERADA: o modelo (fraco) pode esquecer de ECOAR `MEDIA:` na resposta final, mas se
uma tool (generate_pdf/image/video) emitiu o arquivo num passo, o gateway anexa mesmo assim. VOZ é a
exceção (modalidade do bug do áudio-não-pedido) — fica só na lógica de espelho. Achado RODANDO o e2e
de coisas comuns: 'gere um pdf' gerava o PDF mas não chegava."""
from __future__ import annotations

import tempfile

import pytest

from okami.channels.base import Channel
from okami.core import Step, Task, TaskState
from okami.gateway import AgentEndpoint


def _step(output, tool="generate_pdf"):
    return Step(n=1, tool=tool, args={}, output=output, effect=True)


class MediaChannel(Channel):
    name = "telegram"
    supports_media = True

    def __init__(self):
        self.sent = []
        self.media = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append(text)

    def send_media(self, chat_id, path, voice=False, document=False):
        self.media.append((str(path), voice, document))

    def send_audio(self, chat_id, path):
        self.media.append((str(path), True, False))

    def allowed(self, chat_id):
        return True


def _runner_with_steps(result, steps):
    def runner(cfg, ws, goal, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, result
        t.steps = steps
        return t
    return runner


def test_generated_pdf_attached_even_when_model_forgets_media_echo(tmp_path):
    pdf = tmp_path / "relatorio.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # resposta SEM MEDIA: (modelo esqueceu) — mas o passo do generate_pdf emitiu o MEDIA:
    steps = [_step(f'PDF gerado (12 bytes): {pdf}\nMEDIA:"{pdf}"')]
    ch = MediaChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch,
                       run_task=_runner_with_steps("pronto, segue o relatório", steps),
                       spawn=lambda fn: fn())
    ep.handle("7", "gere um pdf")
    assert any(str(pdf) in p for p, _v, _d in ch.media), f"PDF gerado não foi anexado: {ch.media}"


def test_step_media_not_double_sent_when_model_echoes(tmp_path):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    steps = [_step(f'MEDIA:"{pdf}"')]
    ch = MediaChannel()
    # resposta TAMBÉM ecoa o MEDIA: → não pode anexar 2x (dedup por caminho)
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch,
                       run_task=_runner_with_steps(f'segue\nMEDIA:"{pdf}"', steps),
                       spawn=lambda fn: fn())
    ep.handle("7", "gere um pdf")
    assert len([p for p, _v, _d in ch.media if str(pdf) in p]) == 1, f"anexou em duplicata: {ch.media}"


def test_voice_step_media_is_not_auto_attached(tmp_path):
    """text_to_speech num passo emite MEDIA: voice=True; se a resposta é TEXTO, NÃO pode virar áudio
    por varredura (seria o bug do áudio-não-pedido por outro caminho). Voz só via espelho."""
    ogg = tmp_path / "fala.ogg"
    ogg.write_bytes(b"OggS fake")
    steps = [_step(f'voz pronta\nMEDIA:"{ogg}"')]
    ch = MediaChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch,
                       run_task=_runner_with_steps("aqui está", steps),
                       spawn=lambda fn: fn())
    ep.handle("7", "qual a capital da frança?")          # entrada TEXTO
    assert not any(v for _p, v, _d in ch.media), f"áudio não-pedido vazou por varredura: {ch.media}"


def test_missing_step_file_is_skipped(tmp_path):
    """MEDIA: apontando p/ arquivo que não existe (passo intermediário apagado) → não tenta anexar."""
    ghost = tmp_path / "sumiu.pdf"                       # nunca criado
    steps = [_step(f'MEDIA:"{ghost}"')]
    ch = MediaChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch,
                       run_task=_runner_with_steps("ok", steps),
                       spawn=lambda fn: fn())
    ep.handle("7", "faça algo")
    assert not ch.media, f"tentou anexar arquivo inexistente: {ch.media}"


@pytest.fixture(autouse=True)
def _pt(monkeypatch):
    import okami.i18n as _i18n
    _i18n.set_lang("pt")
    yield
    _i18n.set_lang(None)
