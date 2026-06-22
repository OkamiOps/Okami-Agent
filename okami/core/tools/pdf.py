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
    description = ("Gera um PDF NATIVO e RÁPIDO (sem Chromium). Use UM de: `content` (markdown/texto), "
                   "`html` (HTML estilizado com CSS → render fiel via xhtml2pdf), ou `html_path` (lê o HTML "
                   "de um arquivo do workspace — bom p/ template grande). Para o caso comum NÃO use skills de "
                   "Puppeteer (lentas): este caminho resolve em ms. Devolve MEDIA: → o canal anexa o arquivo.")
    args_schema = {"content": "markdown ou texto do documento",
                   "html": "HTML completo (com <style>) — render fiel sem browser",
                   "html_path": "caminho de um arquivo HTML no workspace (alternativa a `html`)",
                   "path": "saída .pdf (default 'documento.pdf')",
                   "title": "título opcional (só no modo markdown)"}
    required = ()

    def run(self, args, ctx: ToolContext) -> ToolResult:
        rel = str(args.get("path") or "documento.pdf").strip() or "documento.pdf"
        if not rel.lower().endswith(".pdf"):
            rel += ".pdf"
        out = Path(ctx.workspace).resolve() / rel
        out.parent.mkdir(parents=True, exist_ok=True)

        # --- caminho HTML→PDF (xhtml2pdf): instantâneo, CSS razoável, SEM Chromium/Puppeteer ---
        html = args.get("html")
        html_path = str(args.get("html_path") or "").strip()
        if html_path and not html:
            try:
                from okami.core.file_safety import safe_path
                hp = safe_path(Path(ctx.workspace).resolve(), html_path, open_fs=getattr(ctx, "open_fs", False))
                html = hp.read_text(encoding="utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                return ToolResult(False, f"não consegui ler html_path '{html_path}': {e}")
        if isinstance(html, str) and html.strip():
            return self._from_html(html, out)

        content = args.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolResult(False, "generate_pdf exige 'content' (markdown), 'html' ou 'html_path'.")
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

    def _from_html(self, html: str, out: Path) -> ToolResult:
        """HTML→PDF via xhtml2pdf (pisa) — pura-Python, render de CSS razoável em ~ms, SEM Chromium.
        É o caminho que evita o dono esperar 15min com skill de Puppeteer p/ um PDF estilizado comum."""
        try:
            from okami.core.lazy_deps import ensure
            ensure("pdf.html")                              # xhtml2pdf (1ª vez instala)
            from xhtml2pdf import pisa
        except Exception as e:  # noqa: BLE001 — sem rede/install desligado → erro CLARO, não trava o turno
            return ToolResult(False, f"HTML→PDF indisponível (precisa de xhtml2pdf): {e}")
        try:
            with open(out, "wb") as fh:
                status = pisa.CreatePDF(html, dest=fh, encoding="utf-8")
            if status.err or not out.exists() or out.stat().st_size == 0:
                return ToolResult(False, f"xhtml2pdf não renderizou o HTML (err={getattr(status, 'err', '?')}). "
                                         "Se o layout é MUITO complexo (fontes embutidas/SVG), use a skill de browser.")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao gerar PDF do HTML: {e}")
        return ToolResult(True, f'PDF gerado do HTML ({out.stat().st_size} bytes): {out}\nMEDIA:"{out}"', effect=True)
