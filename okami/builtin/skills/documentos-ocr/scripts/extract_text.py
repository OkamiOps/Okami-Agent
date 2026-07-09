"""
extract_text.py - extrai texto de PDF/imagem escaneada via pymupdf (pura-Python, ~25MB, sem modelo).

SEM shebang de propósito (o scanner de skills do Okami penaliza scripts com shebang embutido); rode
sempre via `python3 extract_text.py ...`. Sem rede, sem segredo — só leitura de arquivo local.

Comandos:
  python3 extract_text.py <arquivo.pdf>                    - texto de todas as páginas
  python3 extract_text.py <arquivo.pdf> --pages 0-4         - intervalo de páginas (0-indexado)
  python3 extract_text.py <arquivo.pdf> --page 2             - uma página só (0-indexado)
  python3 extract_text.py <arquivo.pdf> --metadata           - nº de páginas + título/autor/etc.
  python3 extract_text.py <imagem.png>                       - extrai texto de imagem (pymupdf lê raster)

Saída sempre em JSON no stdout (uma linha) — igual convenção do edit_pdf.py.

Degrada de forma limpa se pymupdf não estiver instalado: devolve `{"ok": false, "error": ...}`
com a instrução de instalação, em vez de estourar traceback.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def _ok(payload: dict) -> None:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False))


def _import_pymupdf():
    """Import lazy — tenta okami.core.lazy_deps primeiro (instala sob demanda se permitido),
    cai para import direto, e só falha (com instrução clara) se nenhum dos dois resolver."""
    try:
        from okami.core.lazy_deps import ensure
        ensure("pdf.pymupdf")
    except Exception:
        pass  # sem lazy_deps disponível (ou feature não cadastrada) — segue pro import direto
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        _fail(
            "pymupdf não instalado. Rode: pip install pymupdf (ou uv pip install pymupdf). "
            "Cobre PDF de texto e imagem/screenshot; NÃO faz OCR de scan sem camada de texto "
            "(nesse caso, avise o dono que precisaria de um OCR dedicado, ex.: pytesseract)."
        )


def _parse_pages(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    if "-" in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(spec)]


def extract_text(path: str, pages: list[int] | None = None) -> None:
    pymupdf = _import_pymupdf()
    if not Path(path).exists():
        _fail(f"arquivo não encontrado: {path}")
    doc = pymupdf.open(path)
    page_range = range(len(doc)) if pages is None else [p for p in pages if 0 <= p < len(doc)]
    out = []
    for i in page_range:
        out.append({"page": i, "text": doc[i].get_text()})
    _ok({"file": path, "total_pages": len(doc), "pages": out})


def show_metadata(path: str) -> None:
    pymupdf = _import_pymupdf()
    if not Path(path).exists():
        _fail(f"arquivo não encontrado: {path}")
    doc = pymupdf.open(path)
    meta = doc.metadata or {}
    _ok({
        "file": path,
        "pages": len(doc),
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "subject": meta.get("subject", ""),
        "creator": meta.get("creator", ""),
        "producer": meta.get("producer", ""),
        "format": meta.get("format", ""),
    })


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return

    path = args[0]

    if "--metadata" in args:
        show_metadata(path)
        return

    pages = None
    if "--page" in args:
        idx = args.index("--page")
        pages = [int(args[idx + 1])]
    elif "--pages" in args:
        idx = args.index("--pages")
        pages = _parse_pages(args[idx + 1])

    extract_text(path, pages=pages)


if __name__ == "__main__":
    main()
