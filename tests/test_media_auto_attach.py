"""Bug real (2026-07-09): imagem/vídeo gerados mas NUNCA entregues no Telegram porque a saída da tool
não emitia MEDIA:<path> (só o generate_pdf emitia). O gateway anexa varrendo os steps por MEDIA:, então
image/pdf/video TÊM que emitir a tag na saída — não depender do modelo ecoar."""
import inspect, re
from okami.core.tools.agentic import GenerateImage
from okami.core.tools.video import GenerateVideo
import okami.core.tools.pdf as pdfmod


def _success_emits_media(cls_or_mod, cls_name=None):
    src = inspect.getsource(cls_or_mod)
    # toda linha de sucesso (ToolResult(True, ...)) desses geradores deve conter MEDIA:
    hits = re.findall(r"ToolResult\(True,[^\n]*", src)
    assert hits, "nenhum ToolResult(True) encontrado"
    return all("MEDIA:" in h for h in hits)


def test_generate_image_emite_media():
    assert _success_emits_media(GenerateImage)


def test_generate_video_emite_media():
    assert _success_emits_media(GenerateVideo)


def test_generate_pdf_ainda_emite_media():
    assert _success_emits_media(pdfmod)
