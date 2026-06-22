"""Tool `generate_pdf` — o agente CRIA um PDF a partir de markdown/texto.

Faltava capacidade de PDF: sem tool, sem conversor de sistema (pandoc/wkhtmltopdf), sem lib Python.
Pedir "gere um pdf" fazia o modelo PATINAR (toda abordagem falhava: pandoc→not found, reportlab→
ImportError) até o anti-travamento desistir. Aqui ele tem UM caminho confiável: markdown/texto → PDF
via fpdf2 (pura-Python, lazy-install, SEM dep de sistema → roda em VPS/Mac/Windows). Devolve
`MEDIA:<path>` → o gateway anexa o PDF como documento.
"""
from __future__ import annotations

from pathlib import Path

from okami.core.tools.base import Tool, ToolContext, ToolResult


class GeneratePdf(Tool):
    name = "generate_pdf"
    description = ("Gera um PDF a partir de `content` (markdown ou texto) em `path`. Use quando o dono "
                   "pede um documento/relatório EM PDF. Devolve MEDIA: → o canal anexa o arquivo pronto.")
    args_schema = {"content": "markdown ou texto do documento",
                   "path": "saída .pdf (default 'documento.pdf')",
                   "title": "título opcional (vira o cabeçalho do PDF)"}
    required = ("content",)

    def run(self, args, ctx: ToolContext) -> ToolResult:
        content = args.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolResult(False, "generate_pdf exige 'content' (markdown ou texto não-vazio).")
        rel = str(args.get("path") or "documento.pdf").strip() or "documento.pdf"
        if not rel.lower().endswith(".pdf"):
            rel += ".pdf"
        out = Path(ctx.workspace).resolve() / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            from okami.core.lazy_deps import ensure
            ensure("pdf.fpdf")                                  # fpdf2 + markdown (1ª vez instala)
            import markdown as _md
            from fpdf import FPDF
        except Exception as e:  # noqa: BLE001 — sem rede/install desligado → erro CLARO, não trava o turno
            return ToolResult(False, f"PDF indisponível (precisa de fpdf2/markdown): {e}")
        title = str(args.get("title") or "").strip()
        body_md = f"# {title}\n\n{content}" if title else content
        try:
            html = _md.markdown(body_md, extensions=["tables", "fenced_code"])
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("helvetica", size=11)
            try:
                pdf.write_html(html)
            except Exception:  # noqa: BLE001 — HTML que o fpdf não digere (ou char fora do latin-1) → texto puro
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("helvetica", size=11)
                safe = body_md.encode("latin-1", "replace").decode("latin-1")   # core font = latin-1
                pdf.multi_cell(0, 6, safe)
            pdf.output(str(out))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao gerar PDF: {e}")
        return ToolResult(True, f'PDF gerado ({out.stat().st_size} bytes): {out}\nMEDIA:"{out}"', effect=True)
