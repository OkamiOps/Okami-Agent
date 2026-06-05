"""Tools do harness (Fase 1).

Tools nativas (read/write/list/shell) + tools terminais (complete/blocked/need_input).
A `ToolContext` carrega o workspace e o conjunto de arquivos lidos — base do grounding
anti-alucinação (§3.7): não se sobrescreve um arquivo existente que não foi lido.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Variáveis de ambiente sensíveis são REMOVIDAS dos subprocessos do agente (run_shell,
# shell_ok), para que prompt injection / código gerado não consiga exfiltrar credenciais
# (padrão do Hermes). Estamos protegendo chaves de provider, tokens OAuth, AWS, etc.
_SENSITIVE_ENV = re.compile(
    r"(API[_-]?KEY|ACCESS[_-]?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE[_-]?KEY|_PAT$)",
    re.IGNORECASE,
)


def sanitized_env() -> dict[str, str]:
    """Cópia do ambiente sem variáveis sensíveis (chaves/segredos/tokens)."""
    return {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV.search(k)}


@dataclass
class ToolContext:
    workspace: Path
    read_files: set[str] = field(default_factory=set)
    memory: object | None = None  # backend de memória (duck-typed: write/recall)
    skills: dict = field(default_factory=dict)  # nome -> corpo da SKILL.md (progressive disclosure)
    checkpoints: object | None = None  # snapshot antes de escrever → rollback (duck-typed: snapshot)
    spawn: object | None = None  # delega um subtask a um subagente isolado (Callable(goal, agent, model)->str)


@dataclass
class ToolResult:
    ok: bool
    output: str
    effect: bool = False  # houve efeito colateral observável? (alimenta o watchdog §3.3)


class Tool:
    name: str = ""
    description: str = ""
    args_schema: dict[str, str] = {}
    required: tuple[str, ...] = ()   # args obrigatórios (validados pelo harness antes de rodar)
    terminal: bool = False

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        raise NotImplementedError


def _safe_path(ctx: ToolContext, rel: str) -> Path:
    p = (ctx.workspace / rel).resolve()
    # impede escapar do workspace
    if ctx.workspace.resolve() not in p.parents and p != ctx.workspace.resolve():
        raise ValueError(f"caminho fora do workspace: {rel}")
    return p


class ReadFile(Tool):
    name = "read_file"
    description = "Lê um arquivo de texto do workspace."
    args_schema = {"path": "caminho relativo ao workspace"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args["path"]
        try:
            p = _safe_path(ctx, rel)
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ToolResult(False, f"arquivo não existe: {rel}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro ao ler {rel}: {e}")
        ctx.read_files.add(rel)
        return ToolResult(True, text, effect=False)


class WriteFile(Tool):
    name = "write_file"
    description = "Escreve/sobrescreve um arquivo. Para sobrescrever um existente, leia-o antes (grounding)."
    args_schema = {"path": "caminho relativo", "content": "conteúdo completo do arquivo"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args["path"]
        content = args.get("content", "")
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e))
        # Grounding anti-alucinação (§3.7): não sobrescreve existente não-lido.
        if p.exists() and rel not in ctx.read_files:
            return ToolResult(
                False,
                f"'{rel}' já existe e você não o leu. Use read_file antes de sobrescrever (grounding).",
            )
        if ctx.checkpoints is not None:                # snapshot do estado ANTERIOR (rede de segurança)
            try:
                ctx.checkpoints.snapshot(rel)
            except Exception:  # noqa: BLE001 — checkpoint é best-effort, nunca bloqueia a escrita
                pass
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n": evita CRLF dependente de SO em arquivos gerados (portabilidade).
        p.write_text(content, encoding="utf-8", newline="\n")
        ctx.read_files.add(rel)  # acabou de escrever → conhece o conteúdo
        return ToolResult(True, f"escrito {rel} ({len(content)} chars)", effect=True)


class EditFile(Tool):
    name = "edit_file"
    description = ("Edita um arquivo por substituição EXATA de trecho (old→new) — sem reescrever tudo. "
                   "'old' precisa casar literalmente (espaços/indentação) e ser ÚNICO, ou use replace_all.")
    args_schema = {"path": "caminho relativo", "old": "trecho exato a trocar (literal)",
                   "new": "novo trecho", "replace_all": "(opcional) trocar todas as ocorrências"}
    required = ("path", "old")

    def run(self, args, ctx):
        rel = args["path"]
        old = args.get("old", "")
        new = args.get("new", "")
        replace_all = bool(args.get("replace_all", False))
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e))
        if not old:
            return ToolResult(False, "edit_file exige 'old' (trecho a substituir) não-vazio.")
        if not p.exists():
            return ToolResult(False, f"'{rel}' não existe — use write_file para criar.")
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro ao ler {rel}: {e}")
        count = text.count(old)
        if count == 0:
            return ToolResult(False, f"trecho não encontrado em {rel} — precisa ser EXATO (incl. espaços).")
        if count > 1 and not replace_all:
            return ToolResult(False, f"'old' aparece {count}× em {rel} — torne-o único (mais contexto) "
                                     "ou passe replace_all=true.")
        if ctx.checkpoints is not None:                # snapshot antes (rede de segurança / rollback)
            try:
                ctx.checkpoints.snapshot(rel)
            except Exception:  # noqa: BLE001
                pass
        new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        p.write_text(new_text, encoding="utf-8", newline="\n")
        ctx.read_files.add(rel)
        n = count if replace_all else 1
        return ToolResult(True, f"editado {rel} ({n} substituiç{'ões' if n > 1 else 'ão'})", effect=True)


class ListDir(Tool):
    name = "list_dir"
    description = "Lista arquivos/pastas de um diretório do workspace."
    args_schema = {"path": "caminho relativo (use '.' para a raiz)"}

    def run(self, args, ctx):
        rel = args.get("path", ".")
        try:
            p = _safe_path(ctx, rel)
            entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro ao listar {rel}: {e}")
        return ToolResult(True, "\n".join(entries) or "(vazio)", effect=False)


class RunShell(Tool):
    name = "run_shell"
    description = "Executa um comando de shell no workspace (timeout 60s). Sandbox real virá na Fase 12."
    args_schema = {"cmd": "comando a executar"}
    required = ("cmd",)

    def run(self, args, ctx):
        cmd = args["cmd"]
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=str(ctx.workspace),
                capture_output=True, text=True, timeout=60,
                env=sanitized_env(),  # sem credenciais no ambiente (anti-exfiltração)
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"timeout (60s): {cmd}", effect=True)
        out = (r.stdout or "") + (r.stderr or "")
        out = out.strip() or "(sem saída)"
        ok = r.returncode == 0
        return ToolResult(ok, f"exit={r.returncode}\n{out}", effect=True)


class RememberFact(Tool):
    name = "remember"
    description = "Guarda um fato durável na memória de longo prazo (decisões, preferências, etc.)."
    args_schema = {"text": "o fato a lembrar"}
    required = ("text",)

    def run(self, args, ctx):
        if ctx.memory is None:
            return ToolResult(False, "memória não ativa")
        from okami.memory.base import MemoryItem
        ctx.memory.write(MemoryItem(text=args["text"], kind="fact", source="agent"))
        return ToolResult(True, f"lembrado: {args['text'][:80]}", effect=True)


class RecallMemory(Tool):
    name = "recall_memory"
    description = "Busca na memória de longo prazo (fatos, decisões, trechos comprimidos)."
    args_schema = {"query": "o que buscar"}
    required = ("query",)

    def run(self, args, ctx):
        if ctx.memory is None:
            return ToolResult(False, "memória não ativa")
        items = ctx.memory.recall(args.get("query", ""), 5)
        if not items:
            return ToolResult(True, "(nada encontrado na memória)")
        return ToolResult(True, "\n".join(f"- {i.text[:200]}" for i in items))


class RememberUser(Tool):
    name = "remember_user"
    description = "Anota algo durável SOBRE O USUÁRIO em USER.md (preferência, contexto) — sempre no prompt."
    args_schema = {"text": "o fato sobre o usuário"}
    required = ("text",)

    def run(self, args, ctx):
        from okami.memory import files as _f
        _f.append_user(ctx.workspace, args["text"])
        return ToolResult(True, f"USER.md += {args['text'][:80]}", effect=True)


class FinishSetup(Tool):
    name = "finish_setup"
    description = ("Encerra a CONFIGURAÇÃO INICIAL (gênese) do agente — chame SÓ na primeira conversa, "
                  "quando a pessoa estiver satisfeita com sua identidade (ou se ela quiser deixar p/ depois). "
                  "Em 'about_user', passe 1 linha sobre quem ela é (vai pro USER.md).")
    args_schema = {"about_user": "(opc) o que aprendeu sobre a pessoa, p/ o USER.md"}

    def run(self, args, ctx):
        from okami.memory import files as _f
        about = (args.get("about_user") or "").strip()
        if about:
            _f.append_user(ctx.workspace, about)
        marker = ctx.workspace / ".okami" / "genesis.done"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("done\n", encoding="utf-8")
        return ToolResult(True, "configuração inicial concluída ✓", effect=True)


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


# Tools terminais: o loop trata especialmente, mas elas existem para schema/parse.
class Respond(Tool):
    name = "respond"
    description = ("FALA com o usuário (responder, opinar, perguntar, conversar) e encerra o turno. "
                   "É assim que você conversa — use sempre que for só diálogo, sem precisar agir.")
    args_schema = {"message": "sua mensagem ao usuário, no seu tom (VOICE/PERSONA)"}
    required = ("message",)
    terminal = True


class TaskComplete(Tool):
    name = "task_complete"
    description = "Conclui um TRABALHO com critérios. Só é aceito se os critérios de saída forem verificados."
    args_schema = {"summary": "resumo do que foi feito"}
    terminal = True


class TaskBlocked(Tool):
    name = "task_blocked"
    description = "Declara que está bloqueado, com a razão."
    args_schema = {"reason": "por que está bloqueado"}
    required = ("reason",)
    terminal = True


class NeedInput(Tool):
    name = "need_input"
    description = "Pede uma informação ao usuário para poder continuar."
    args_schema = {"question": "pergunta ao usuário"}
    required = ("question",)
    terminal = True


def default_registry() -> dict[str, Tool]:
    tools = [Respond(), ReadFile(), WriteFile(), EditFile(), ListDir(), RunShell(), RememberFact(), RecallMemory(),
             RememberUser(), UseSkill(), Spawn(), Browse(), GenerateImage(), FinishSetup(),
             TaskComplete(), TaskBlocked(), NeedInput()]
    return {t.name: t for t in tools}
