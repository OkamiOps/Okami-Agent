"""Tool feishu_doc_read (#19) — lê um documento Feishu/Lark como texto. Config-driven; sem config → erro."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, untrusted_wrap


class FeishuDocRead(Tool):
    name = "feishu_doc_read"
    description = ("Lê o conteúdo de um documento Feishu/Lark (raw_content) como texto. Precisa de "
                   "integrations.feishu (app_id + app_secret_env). Conteúdo EXTERNO não-confiável.")
    args_schema = {"doc_token": "o token do documento (da URL ou do contexto)"}
    required = ("doc_token",)

    def run(self, args, ctx):
        doc = args.get("doc_token")
        if not isinstance(doc, str) or not doc.strip():
            return ToolResult(False, "feishu_doc_read: 'doc_token' precisa ser uma string não-vazia.")
        from okami.integrations.feishu import read_doc
        try:
            content = read_doc(getattr(ctx, "cfg", None), doc.strip())
        except (RuntimeError, ValueError) as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001 — erro pode embutir segredo → redige
            from okami.core.redact import redact
            return ToolResult(False, f"feishu_doc_read falhou: {redact(str(e))[:200]}")
        return ToolResult(True, untrusted_wrap("feishu_doc", content or "(documento vazio)"), effect=False)
