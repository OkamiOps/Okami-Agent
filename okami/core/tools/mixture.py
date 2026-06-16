"""Tool mixture_of_agents (#17) — roteia um problema difícil por vários providers e sintetiza a melhor
resposta. Amplificação de raciocínio sob a constraint assinatura-only (usa os providers já configurados)."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult


class MixtureOfAgents(Tool):
    name = "mixture_of_agents"
    description = ("Roteia um problema DIFÍCIL por vários modelos (os providers configurados) em paralelo "
                   "e sintetiza UMA resposta refinada com o mais forte. Use com PARCIMÔNIA — faz N+1 "
                   "chamadas — só para problemas genuinamente difíceis (matemática, algoritmos, análise "
                   "multi-passo) que se beneficiam de perspectivas diversas.")
    args_schema = {"prompt": "o problema difícil a resolver com múltiplos modelos"}
    required = ("prompt",)

    def run(self, args, ctx):
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(False, "mixture_of_agents: 'prompt' precisa ser uma string não-vazia.")
        cfg = getattr(ctx, "cfg", None)
        if cfg is None:
            return ToolResult(False, "mixture_of_agents: sem config de providers no contexto.")
        from okami.llm import mixture as _mx
        res = _mx.run_mixture(cfg, prompt)
        if not res.get("success"):
            return ToolResult(False, res.get("response") or "mixture falhou.")
        used = res.get("models_used", {})
        refs = ", ".join(used.get("reference_providers", []))
        header = f"[mixture: {res.get('n_references', 0)} referências ({refs}) → síntese por {used.get('aggregator', '?')}]"
        return ToolResult(True, f"{header}\n\n{res['response']}", effect=False)
