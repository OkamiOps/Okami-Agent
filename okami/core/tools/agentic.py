"""Tools agênticas: use_skill, spawn (subagente), browse, generate_image."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult, _safe_path,
)


class UseSkill(Tool):
    name = "use_skill"
    description = "Carrega o procedimento de uma skill do CATÁLOGO (siga-o à risca). Use quando a tarefa casar com uma skill."
    args_schema = {"name": "nome da skill no catálogo"}
    required = ("name",)

    def run(self, args, ctx):
        body = ctx.skills.get(args["name"])
        if not body:
            disp = ", ".join(ctx.skills) or "(nenhuma)"
            return ToolResult(False, f"skill '{args['name']}' não está no catálogo. Disponíveis: {disp}")
        return ToolResult(True, f"SKILL '{args['name']}' (siga este procedimento):\n{body}")


class ManageSkill(Tool):
    name = "manage_skill"
    description = ("Cria/edita uma SKILL reutilizável (procedimento de uma CLASSE de tarefa) — use no review "
                   "de auto-aprimoramento. Nome no NÍVEL DE CLASSE (kebab-case, ≤3 palavras): NUNCA a frase do "
                   "pedido, número de PR, string de erro ou codinome. action=create|edit. Corpo em markdown "
                   "(## Quando usar / ## Como / ## Cuidados).")
    args_schema = {"action": "create|edit", "name": "kebab-case curto (nível de classe)",
                   "description": "1 linha (≤120 chars)", "body": "markdown do procedimento"}
    required = ("action", "name", "body")

    def run(self, args, ctx):
        import re as _re
        from pathlib import Path

        import yaml as _yaml

        from okami.skills.skill_security import Severity, scan_text
        root = getattr(ctx, "skills_dir", None)
        if not root:
            return ToolResult(False, "manage_skill indisponível neste contexto (sem skills_dir).")
        name = str(args.get("name", "")).strip().lower()
        if not _re.match(r"^[a-z0-9][a-z0-9._-]{1,47}$", name) or name.count("-") > 3:
            return ToolResult(False, "nome inválido: kebab-case curto (≤48 chars, ≤3 hífens), nível de CLASSE "
                              "(não a frase do pedido / PR / erro / codinome).")
        body = str(args.get("body", "")).strip()
        if len(body) < 20:
            return ToolResult(False, "corpo curto demais — descreva ## Quando usar / ## Como / ## Cuidados.")
        if any(f.severity >= Severity.HIGH for f in scan_text(name, body)):
            return ToolResult(False, "skill bloqueada pelo scan de segurança (HIGH) — reescreva sem o padrão de risco.")
        d = Path(root) / name
        f = d / "SKILL.md"
        if args.get("action") == "create" and f.exists():
            return ToolResult(False, f"skill '{name}' já existe — use action=edit p/ melhorar.")
        meta = {"name": name, "description": (str(args.get("description", "")).strip() or name)[:120],
                "origin": "agent"}      # provenance: o curator só mexe no que o agente criou
        try:
            d.mkdir(parents=True, exist_ok=True)
            f.write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n"
                         + body + "\n", encoding="utf-8", newline="\n")
        except OSError as e:
            return ToolResult(False, f"falha ao gravar skill: {e}")
        return ToolResult(True, f"skill '{name}' {args.get('action')} (origin: agent)", effect=True)


class Spawn(Tool):
    name = "spawn"
    description = ("Delega um SUBTASK a um subagente ISOLADO (contexto próprio) e recebe o resultado. "
                   "Use p/ paralelizar/especializar (ex.: 'agent: ui' p/ frontend). Não abuse — tem custo.")
    args_schema = {"goal": "o subtask", "agent": "(opcional) id do agente", "model": "(opcional) modelo"}
    required = ("goal",)

    def run(self, args, ctx):
        if ctx.spawn is None:
            return ToolResult(False, "spawn indisponível neste contexto.")
        try:
            out = ctx.spawn(args["goal"], args.get("agent"), args.get("model"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"subagente falhou: {e}")
        return ToolResult(True, f"SUBAGENTE devolveu:\n{out}", effect=True)


class Browse(Tool):
    name = "browse"
    description = "Abre uma URL e lê o texto. Com Playwright também: action=click|fill|screenshot."
    args_schema = {"url": "URL", "action": "read|click|fill|screenshot", "selector": "(opc)", "text": "(opc)"}
    required = ("url",)

    def run(self, args, ctx):
        try:
            from okami.integrations.browser import browse
            out = browse(args["url"], args.get("action", "read"), args.get("selector"), args.get("text"),
                         args.get("screenshot"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"browse falhou: {e}")
        return ToolResult(True, out, effect=args.get("action") in ("click", "fill"))


class GenerateImage(Tool):
    name = "generate_image"
    description = ("Gera uma IMAGEM (gpt-image-2 via assinatura Codex). Sem 'references' = imagem nova; "
                   "com 'references' (caminhos no workspace) = MANDA essas imagens + o prompt p/ o modelo "
                   "transformar (ex.: virar infográfico) — NÃO edite o arquivo você mesmo.")
    args_schema = {"prompt": "o que gerar", "path": "saída (.png)", "references": "(opc) lista de imagens base"}
    required = ("prompt", "path")

    def run(self, args, ctx):
        try:
            p = _safe_path(ctx, args["path"])
            refs = []
            for r in (args.get("references") or []):
                refs.append(str(_safe_path(ctx, r)))      # referências também dentro do workspace
        except ValueError as e:
            return ToolResult(False, str(e))
        try:
            from okami.llm.imagegen import generate_image
            generate_image(args["prompt"], str(p), references=refs or None)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao gerar imagem: {e}")
        how = f" (com {len(refs)} referência(s))" if refs else ""
        return ToolResult(True, f"imagem gerada{how}: {args['path']}", effect=True)
