"""
edit_pdf.py - editor de PDF via linha de comando, pura-Python (pypdf + fpdf2).

SEM shebang de propósito (o scanner de skills do Okami penaliza scripts com shebang embutido); rode
sempre via `python3 edit_pdf.py ...`.

Comandos:
  info      <arquivo.pdf>                                   - nº de páginas + metadata atual
  extract   <arquivo.pdf> [--page N]                          - texto de uma página (ou todas)
  metadata  <in.pdf> <out.pdf> [--title T] [--author A] [--subject S] [--keywords K]
  patch     <in.pdf> <out.pdf> --page N --rect x0,y0,x1,y1 --text "novo texto" [--font-size 11]
            - APAGA a área (retângulo branco) e ESCREVE o texto novo por cima. Uso: trocar um título,
              corrigir uma data, mudar um nome — SEM precisar entender o content stream do PDF.
  delete-page <in.pdf> <out.pdf> --page N
  rotate    <in.pdf> <out.pdf> --page N --degrees 90
  merge     <out.pdf> <in1.pdf> <in2.pdf> [...]
  split     <in.pdf> <out_dir> [--prefix pagina]

Saída sempre em JSON no stdout (uma linha) — igual convenção do stocks_client.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def _ok(payload: dict) -> None:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False))


def _import_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter
        return PdfReader, PdfWriter
    except ImportError:
        _fail("pypdf não instalado. Rode: pip install 'pypdf>=4.0.0' (ou deixe o Okami "
             "instalar via lazy_deps.ensure('pdf.edit')).")


def cmd_info(args) -> None:
    PdfReader, _ = _import_pypdf()
    r = PdfReader(args.file)
    meta = {k.lstrip("/"): v for k, v in (r.metadata or {}).items()} if r.metadata else {}
    _ok({"file": args.file, "pages": len(r.pages), "metadata": meta,
        "encrypted": r.is_encrypted})


def cmd_extract(args) -> None:
    PdfReader, _ = _import_pypdf()
    r = PdfReader(args.file)
    if args.page is not None:
        idx = args.page - 1
        if not (0 <= idx < len(r.pages)):
            _fail(f"página {args.page} fora do intervalo (o PDF tem {len(r.pages)} páginas).")
        _ok({"page": args.page, "text": r.pages[idx].extract_text() or ""})
    else:
        pages = [{"page": i + 1, "text": p.extract_text() or ""} for i, p in enumerate(r.pages)]
        _ok({"pages": pages})


def cmd_metadata(args) -> None:
    PdfReader, PdfWriter = _import_pypdf()
    r = PdfReader(args.infile)
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    meta = dict(r.metadata or {})
    if args.title is not None:
        meta["/Title"] = args.title
    if args.author is not None:
        meta["/Author"] = args.author
    if args.subject is not None:
        meta["/Subject"] = args.subject
    if args.keywords is not None:
        meta["/Keywords"] = args.keywords
    w.add_metadata(meta)
    _write(w, args.outfile)
    _ok({"outfile": args.outfile, "metadata": {k.lstrip("/"): v for k, v in meta.items()}})


def cmd_patch(args) -> None:
    """Sobrepõe um retângulo branco + texto novo numa página — a forma prática de 'editar texto' sem
    parsear o content stream do PDF (pypdf não edita glyphs in-place; overlay é a abordagem padrão da
    indústria pra correções pontuais: título, data, nome)."""
    PdfReader, PdfWriter = _import_pypdf()
    try:
        from okami.core.lazy_deps import ensure
        ensure("pdf.fpdf")
        from fpdf import FPDF
    except Exception as e:  # noqa: BLE001
        _fail(f"overlay precisa de fpdf2 (já é dep do Okami p/ generate_pdf): {e}")
        return

    r = PdfReader(args.infile)
    idx = args.page - 1
    if not (0 <= idx < len(r.pages)):
        _fail(f"página {args.page} fora do intervalo (o PDF tem {len(r.pages)} páginas).")
    page = r.pages[idx]
    pw, ph = float(page.mediabox.width), float(page.mediabox.height)

    try:
        x0, y0, x1, y1 = (float(v) for v in args.rect.split(","))
    except ValueError:
        _fail("--rect precisa ser 'x0,y0,x1,y1' (origem no canto INFERIOR esquerdo, unidades = pontos PDF).")
        return

    overlay_path = Path(args.infile).with_suffix(".patch_overlay.pdf")
    pdf = FPDF(unit="pt", format=(pw, ph))
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)
    # fpdf mede Y do TOPO pra baixo; PDF/pypdf medem do FUNDO — converte.
    fx0, fy0, fx1, fy1 = x0, ph - y1, x1, ph - y0
    pdf.rect(fx0, fy0, fx1 - fx0, fy1 - fy0, style="F")
    pdf.set_font("helvetica", size=args.font_size)
    pdf.set_xy(fx0 + 2, fy0 + 2)
    pdf.multi_cell(fx1 - fx0 - 4, args.font_size * 1.2, args.text)
    pdf.output(str(overlay_path))

    overlay_reader = PdfReader(str(overlay_path))
    page.merge_page(overlay_reader.pages[0])

    w = PdfWriter()
    for i, p in enumerate(r.pages):
        w.add_page(page if i == idx else p)
    _write(w, args.outfile)
    overlay_path.unlink(missing_ok=True)
    _ok({"outfile": args.outfile, "page": args.page, "rect": [x0, y0, x1, y1]})


def cmd_delete_page(args) -> None:
    PdfReader, PdfWriter = _import_pypdf()
    r = PdfReader(args.infile)
    idx = args.page - 1
    if not (0 <= idx < len(r.pages)):
        _fail(f"página {args.page} fora do intervalo (o PDF tem {len(r.pages)} páginas).")
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i != idx:
            w.add_page(p)
    _write(w, args.outfile)
    _ok({"outfile": args.outfile, "removed_page": args.page, "pages": len(w.pages)})


def cmd_rotate(args) -> None:
    PdfReader, PdfWriter = _import_pypdf()
    r = PdfReader(args.infile)
    idx = args.page - 1
    if not (0 <= idx < len(r.pages)):
        _fail(f"página {args.page} fora do intervalo (o PDF tem {len(r.pages)} páginas).")
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i == idx:
            p.rotate(args.degrees)
        w.add_page(p)
    _write(w, args.outfile)
    _ok({"outfile": args.outfile, "page": args.page, "degrees": args.degrees})


def cmd_merge(args) -> None:
    PdfReader, PdfWriter = _import_pypdf()
    w = PdfWriter()
    for f in args.infiles:
        r = PdfReader(f)
        for p in r.pages:
            w.add_page(p)
    _write(w, args.outfile)
    _ok({"outfile": args.outfile, "sources": args.infiles, "pages": len(w.pages)})


def cmd_split(args) -> None:
    PdfReader, PdfWriter = _import_pypdf()
    r = PdfReader(args.infile)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for i, p in enumerate(r.pages, start=1):
        w = PdfWriter()
        w.add_page(p)
        out = out_dir / f"{args.prefix}_{i:03d}.pdf"
        _write(w, str(out))
        outputs.append(str(out))
    _ok({"out_dir": str(out_dir), "files": outputs})


def _write(writer, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        writer.write(f)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Editor de PDF pura-Python (pypdf + fpdf2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info")
    p.add_argument("file")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("extract")
    p.add_argument("file")
    p.add_argument("--page", type=int, default=None)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("metadata")
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("--title", default=None)
    p.add_argument("--author", default=None)
    p.add_argument("--subject", default=None)
    p.add_argument("--keywords", default=None)
    p.set_defaults(func=cmd_metadata)

    p = sub.add_parser("patch")
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--rect", required=True, help="x0,y0,x1,y1 em pontos PDF (origem inferior-esquerda)")
    p.add_argument("--text", required=True)
    p.add_argument("--font-size", type=float, default=11.0)
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("delete-page")
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("--page", type=int, required=True)
    p.set_defaults(func=cmd_delete_page)

    p = sub.add_parser("rotate")
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--degrees", type=int, default=90)
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("merge")
    p.add_argument("outfile")
    p.add_argument("infiles", nargs="+")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("split")
    p.add_argument("infile")
    p.add_argument("out_dir")
    p.add_argument("--prefix", default="pagina")
    p.set_defaults(func=cmd_split)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
