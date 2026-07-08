"""Tool web_extract (pesquisa #6 item 3) — lê uma página e resume via modelo auxiliar (denso, fiel)."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, untrusted_wrap


class WebExtract(Tool):
    name = "web_extract"
    description = ("Lê uma página web e devolve o conteúdo RESUMIDO (página grande é chunkada e "
                   "resumida por um modelo auxiliar, preservando fatos/código) — melhor que browse "
                   "para extrair informação de páginas longas. Conteúdo EXTERNO não-confiável.")
    args_schema = {"url": "a URL a extrair", "max_chars": "(opc) teto sem resumir (default 8000)"}
    required = ("url",)

    def run(self, args, ctx):
        from okami.integrations.web import _EXTRACT_SUMMARIZE_PROMPT, web_extract
        url = args.get("url")
        if not isinstance(url, str) or not url.strip():
            return ToolResult(False, "web_extract: 'url' precisa ser uma string não-vazia.")
        try:
            max_chars = int(args.get("max_chars") or 8000)
        except (TypeError, ValueError):
            max_chars = 8000

        summarize = None
        cfg = getattr(ctx, "cfg", None)
        if cfg is not None:                           # sumariza via modelo auxiliar barato (task 'extract')
            from okami.llm.aux import aux_complete

            def summarize(txt: str) -> str:
                return aux_complete(cfg, "extract", [
                    {"role": "system", "content": _EXTRACT_SUMMARIZE_PROMPT},
                    {"role": "user", "content": txt}], max_tokens=800)
        workspace = getattr(ctx, "workspace", None)   # cache do texto cru vai p/ <workspace>/.okami/webcache
        try:
            out = web_extract(url, max_chars=max_chars, summarize=summarize,
                              workspace=str(workspace) if workspace else ".")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"web_extract falhou: {e}")
        return ToolResult(True, untrusted_wrap("web_extract", out), effect=False)
