"""Tool generate_video (#18) — gera um vídeo via provider configurado (media.video). Espelha o
generate_image: o caminho de saída é jaulado no workspace; sem config → indisponível."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult


class GenerateVideo(Tool):
    name = "generate_video"
    description = ("Gera um VÍDEO a partir de um prompt (e opcionalmente uma imagem base) via o provider "
                   "de vídeo configurado (media.video — FAL/Replicate/Veo/Kling…). Sem configuração, "
                   "a tool fica indisponível.")
    args_schema = {"prompt": "o que gerar", "path": "saída (.mp4)", "image": "(opc) imagem base (caminho no workspace)"}
    required = ("prompt", "path")

    def run(self, args, ctx):
        from okami.core.tools.base import _safe_path
        cfg = getattr(ctx, "cfg", None)
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(False, "generate_video: 'prompt' precisa ser uma string não-vazia.")
        try:
            out = _safe_path(ctx, args["path"])
            image = str(_safe_path(ctx, args["image"])) if args.get("image") else None
        except (ValueError, KeyError) as e:
            return ToolResult(False, str(e))
        from okami.llm.videogen import generate_video
        try:
            generate_video(cfg, prompt, str(out), image=image)
        except RuntimeError as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao gerar vídeo: {e}")
        how = " (a partir de imagem)" if image else ""
        return ToolResult(True, f"vídeo gerado{how}: {args['path']}", effect=True)
