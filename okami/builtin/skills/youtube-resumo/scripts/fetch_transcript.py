"""
fetch_transcript.py - baixa a transcrição de um vídeo do YouTube e devolve JSON no stdout.

SEM shebang de propósito (o scanner de skills do Okami penaliza scripts com shebang embutido); rode
sempre via `python3 fetch_transcript.py ...`. Faz UMA chamada de rede pública (busca de legenda do
próprio YouTube) — sem variável de segredo/credencial neste arquivo, só leitura de conteúdo público.

Estratégia em duas camadas:
  1. Se `youtube-transcript-api` estiver instalado (lazy-dep opcional, mais robusto e mantido),
     usa ela.
  2. Senão, cai para busca via `urllib` puro (stdlib) na página pública do vídeo: extrai a lista de
     faixas de legenda embutida no HTML e baixa o XML da faixa escolhida.

Nenhuma das duas camadas usa chave de API nem autenticação — tudo é conteúdo público do vídeo.

Uso:
    python3 fetch_transcript.py <url_ou_id>
    python3 fetch_transcript.py <url_ou_id> --language pt,en
    python3 fetch_transcript.py <url_ou_id> --timestamps
    python3 fetch_transcript.py <url_ou_id> --text-only [--timestamps]

Instalar a dependência opcional (melhora robustez, não é obrigatória):
    pip install youtube-transcript-api
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from xml.etree import ElementTree

_UA = "Mozilla/5.0 (compatible; OkamiAgent/1.0; +https://example.invalid/bot)"
_ID_PATTERNS = (
    r"(?:v=|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})",
    r"^([a-zA-Z0-9_-]{11})$",
)


def extract_video_id(url_or_id: str) -> str:
    """Extrai o ID de 11 caracteres de qualquer formato de URL do YouTube (ou devolve como veio,
    se já for um ID)."""
    s = url_or_id.strip()
    for pattern in _ID_PATTERNS:
        m = re.search(pattern, s)
        if m:
            return m.group(1)
    return s


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fetch_via_library(video_id: str, languages: list[str] | None) -> list[dict]:
    """Camada 1: youtube-transcript-api, se instalado. Levanta ImportError se ausente — o chamador
    decide se cai pra camada 2."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    result = api.fetch(video_id, languages=languages) if languages else api.fetch(video_id)
    return [{"text": seg.text, "start": seg.start, "duration": seg.duration} for seg in result]


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_via_urllib(video_id: str, languages: list[str] | None) -> list[dict]:
    """Camada 2 (stdlib puro): raspa a lista de faixas de legenda da própria página pública do
    vídeo e baixa o XML da faixa escolhida. Sem chave de API, sem login — conteúdo público."""
    page = _http_get(f"https://www.youtube.com/watch?v={video_id}&hl=en")
    m = re.search(r'"captionTracks":(\[.*?\])(?=,"(?:audioTracks|translationLanguages)")', page)
    if not m:
        raise LookupError("legendas não encontradas na página (provavelmente desativadas para este vídeo)")
    tracks = json.loads(m.group(1))
    if not tracks:
        raise LookupError("legendas não encontradas na página (provavelmente desativadas para este vídeo)")

    chosen = None
    if languages:
        by_lang = {t.get("languageCode", ""): t for t in tracks}
        for lang in languages:
            if lang in by_lang:
                chosen = by_lang[lang]
                break
    if chosen is None:
        chosen = tracks[0]

    base_url = html.unescape(chosen["baseUrl"])
    xml_text = _http_get(base_url)
    if not xml_text.strip():
        raise LookupError(
            "o YouTube não devolveu o conteúdo da legenda (proteção anti-scraping do lado deles). "
            "Instale youtube-transcript-api para um método mais robusto: pip install youtube-transcript-api"
        )
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as e:
        raise LookupError(
            f"resposta de legenda em formato inesperado ({e}). "
            "Instale youtube-transcript-api para um método mais robusto: pip install youtube-transcript-api"
        ) from e

    segments = []
    for node in root.findall("text"):
        text = html.unescape(node.text or "").replace("\n", " ").strip()
        if not text:
            continue
        start = float(node.get("start", "0"))
        duration = float(node.get("dur", "0"))
        segments.append({"text": text, "start": start, "duration": duration})
    return segments


def fetch_transcript(video_id: str, languages: list[str] | None) -> tuple[list[dict], str]:
    """Devolve (segmentos, camada_usada). Tenta a lib primeiro, cai pro urllib puro."""
    try:
        return _fetch_via_library(video_id, languages), "youtube-transcript-api"
    except ImportError:
        pass
    return _fetch_via_urllib(video_id, languages), "urllib"


def main() -> None:
    parser = argparse.ArgumentParser(description="Baixa a transcrição de um vídeo do YouTube")
    parser.add_argument("url", help="URL do YouTube ou ID do vídeo")
    parser.add_argument("--language", "-l", default=None,
                         help="Códigos de idioma separados por vírgula (ex.: pt,en). Padrão: qualquer um disponível")
    parser.add_argument("--timestamps", "-t", action="store_true", help="Inclui texto com timestamp na saída")
    parser.add_argument("--text-only", action="store_true", help="Imprime texto puro em vez de JSON")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    languages = [x.strip() for x in args.language.split(",")] if args.language else None

    try:
        segments, source = fetch_transcript(video_id, languages)
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "disab" in low or "não encontrad" in low:
            print(json.dumps({"ok": False, "error": "Transcrição indisponível ou desativada para este vídeo."}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        sys.exit(1)

    if not segments:
        print(json.dumps({"ok": False, "error": "transcrição vazia (sem segmentos)."}, ensure_ascii=False))
        sys.exit(1)

    full_text = " ".join(seg["text"] for seg in segments)
    timestamped = "\n".join(f"{format_timestamp(seg['start'])} {seg['text']}" for seg in segments)

    if args.text_only:
        print(timestamped if args.timestamps else full_text)
        return

    result = {
        "ok": True,
        "video_id": video_id,
        "source": source,
        "segment_count": len(segments),
        "duration": format_timestamp(segments[-1]["start"] + segments[-1]["duration"]),
        "full_text": full_text,
    }
    if args.timestamps:
        result["timestamped_text"] = timestamped

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
