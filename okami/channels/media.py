"""Convenção MEDIA:<path> (estilo Hermes): o agente inclui `MEDIA:/caminho/arquivo.ext` na
resposta e o gateway converte em anexo nativo do canal. Channel-agnóstico — o roteamento
por tipo (foto/documento/vídeo/voz) fica em cada canal (ex.: telegram.send_media)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Conjuntos por tipo de entrega (espelham o que o Bot API aceita em cada método).
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}      # sendPhoto (svg não: vira documento)
ANIMATION_EXTS = {"gif"}                                         # sendAnimation
VIDEO_EXTS = {"mp4", "mov", "avi", "mkv", "webm", "3gp"}         # sendVideo
VOICE_EXTS = {"ogg", "opus"}                                     # sendVoice (só com [[audio_as_voice]])
AUDIO_EXTS = {"mp3", "m4a", "wav", "flac", "aac"}                # sendAudio aceita só mp3/m4a; resto → doc
DOC_EXTS = {
    "pdf", "txt", "md", "csv", "tsv", "json", "xml", "html", "htm", "yaml", "yml", "log", "svg",
    "docx", "doc", "odt", "rtf", "xlsx", "xls", "ods", "pptx", "ppt", "odp", "key",
    "zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "epub", "apk", "ipa", "py", "sh",
}
ALL_EXTS = IMAGE_EXTS | ANIMATION_EXTS | VIDEO_EXTS | VOICE_EXTS | AUDIO_EXTS | DOC_EXTS

_EXT_ALT = "|".join(sorted(ALL_EXTS))
# Caminho entre aspas (pode ter espaço) OU caminho "cru" SEM espaço iniciando em / ~/ X:\ e
# terminando numa extensão conhecida — extensão desconhecida NÃO extrai (fica no texto, sem perda).
_MEDIA_RE = re.compile(
    r'''MEDIA:\s*(?P<path>"[^"\n]+"|'[^'\n]+'|'''
    r'''(?:~/|/|[A-Za-z]:[/\\])\S+?\.(?:''' + _EXT_ALT + r'''))'''
    r'''(?=[\s"',;:)\]}]|$)''',
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

VOICE_DIRECTIVE = "[[audio_as_voice]]"     # áudio .ogg/.opus vira BOLHA DE VOZ (não arquivo)
DOCUMENT_DIRECTIVE = "[[as_document]]"     # imagem vira DOCUMENTO (sem recompressão do Telegram)


@dataclass
class Media:
    path: str
    voice: bool = False
    document: bool = False


def extract_media(text: str) -> tuple[str, list[Media]]:
    """Extrai os anexos MEDIA: do texto. Devolve (texto_limpo, [Media…]).

    Tags dentro de código (``` … ``` ou `…`) são EXEMPLO, não pedido de envio — ficam no texto."""
    work = text or ""
    protected: dict[str, str] = {}

    def _stash(m: re.Match) -> str:
        key = f"\x00OKMEDIA{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    work = _FENCE_RE.sub(_stash, work)
    work = _INLINE_CODE_RE.sub(_stash, work)

    voice_all = VOICE_DIRECTIVE in work
    doc_all = DOCUMENT_DIRECTIVE in work
    work = work.replace(VOICE_DIRECTIVE, "").replace(DOCUMENT_DIRECTIVE, "")

    items: list[Media] = []

    def _take(m: re.Match) -> str:
        p = m.group("path").strip()
        if len(p) >= 2 and p[0] in "\"'" and p[-1] == p[0]:
            p = p[1:-1]
        p = os.path.expanduser(p)
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        items.append(Media(p, voice=voice_all and ext in (VOICE_EXTS | AUDIO_EXTS),
                           document=doc_all))
        return ""

    clean = _MEDIA_RE.sub(_take, work)
    for key, original in protected.items():
        clean = clean.replace(key, original)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, items
