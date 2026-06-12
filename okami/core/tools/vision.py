"""Tool vision_analyze (pesquisa #6 item 4) — analisa uma imagem do workspace via modelo auxiliar."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, _safe_path


class VisionAnalyze(Tool):
    name = "vision_analyze"
    description = ("Analisa uma IMAGEM (screenshot, foto, gráfico, diagrama) e responde sobre ela — "
                   "OCR, descrição, leitura de números. Roteia por um modelo auxiliar com visão, então "
                   "funciona mesmo se o seu modelo principal for só de texto. Passe o caminho da imagem "
                   "no workspace e o que você quer saber.")
    args_schema = {"path": "caminho da imagem no workspace", "prompt": "o que analisar/perguntar sobre ela"}
    required = ("path", "prompt")

    def run(self, args, ctx):
        cfg = getattr(ctx, "cfg", None)
        if cfg is None:
            return ToolResult(False, "vision_analyze indisponível: sem config p/ rotear ao modelo auxiliar.")
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "vision_analyze: 'path' precisa ser uma string não-vazia.")
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e))
        from okami.llm.vision import analyze_image
        try:
            out = analyze_image(cfg, str(p), str(args.get("prompt") or ""))
        except Exception as e:  # noqa: BLE001 — modelo auxiliar indisponível/erro
            return ToolResult(False, f"vision_analyze falhou: {e}")
        ctx.read_files.add(rel)
        return ToolResult(True, out or "(o modelo de visão não retornou nada)", effect=False)
