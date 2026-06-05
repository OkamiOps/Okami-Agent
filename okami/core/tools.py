"""Tools do harness (Fase 1).

Tools nativas (read/write/list/shell) + tools terminais (complete/blocked/need_input).
A `ToolContext` carrega o workspace e o conjunto de arquivos lidos — base do grounding
anti-alucinação (§3.7): não se sobrescreve um arquivo existente que não foi lido.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Variáveis de ambiente sensíveis são REMOVIDAS dos subprocessos do agente (run_shell,
# shell_ok), para que prompt injection / código gerado não consiga exfiltrar credenciais
# (padrão do Hermes). Estamos protegendo chaves de provider, tokens OAuth, AWS, etc.
_SENSITIVE_ENV = re.compile(
    r"(API[_-]?KEY|ACCESS[_-]?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE[_-]?KEY"
    r"|AUTH|SESSION|COOKIE|_PAT$)",   # +AUTH/SESSION/COOKIE (igual ao _SECRET_ENV_NAMES do Hermes)
    re.IGNORECASE,
)


def sanitized_env() -> dict[str, str]:
    """Cópia do ambiente sem variáveis sensíveis (chaves/segredos/tokens)."""
    return {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV.search(k)}


# #2 do self-review do Okami: shell read-only NÃO conta como progresso (não engana o watchdog §3.3).
_SHELL_MUTATES = re.compile(
    r"\b(rm|rmdir|mv|cp|mkdir|touch|ln|dd|chmod|chown|tee|truncate|install|make|cmake|npm|pnpm|yarn|"
    r"pip|pip3|uv|cargo|go|gradle|mvn|docker|kubectl|terraform|apt|brew|systemctl|kill|pkill)\b"
    r"|>>?|sed\s+-i|git\s+(commit|push|add|merge|rebase|reset|checkout|clean|stash|tag|init|rm|mv|apply)",
    re.IGNORECASE,
)
_SHELL_READONLY = {"ls", "find", "grep", "rg", "cat", "head", "tail", "pwd", "echo", "which", "wc",
                   "file", "stat", "tree", "awk", "du", "df", "ps", "env", "printenv", "date",
                   "whoami", "uname", "hostname", "sort", "uniq", "cut", "diff", "sed"}


# Política de leitura sensível (P0.1): o shell NÃO confina o FS de verdade (cwd=workspace, mas
# `cat ~/.ssh/id_rsa` escapa via expansão). Bloqueia comando que toca segredo conhecido — defesa em
# profundidade (yolo/docker liberam). Não é à prova de ofuscação, mas mata o `cat .env`/exfil óbvio.
_SENSITIVE_PATH = re.compile(
    r"\.env\b|\.okami/credentials|\.codex/auth|[/~.]ssh\b|[/~.]aws\b|\.gnupg|id_rsa|id_ed25519|"
    r"\.pem\b|\.key\b|/etc/(passwd|shadow)|credentials\.json|\.netrc|\.npmrc|\.pypirc|"
    r"secrets?\.(env|json|ya?ml)",
    re.IGNORECASE,
)


def shell_has_effect(cmd: str) -> bool:
    """True se o comando MUTA estado (= progresso real); False se for só leitura/inspeção."""
    if _SHELL_MUTATES.search(cmd):
        return True
    for part in re.split(r"[|&;]+", cmd):              # cada subcomando (pipe/and/seq)
        tok = part.strip().split()
        if not tok:
            continue
        head = tok[0].lstrip("(").lower()
        if head == "git" and len(tok) > 1 and tok[1] in (
                "status", "log", "diff", "show", "branch", "ls-files", "rev-parse", "blame"):
            continue
        if head in _SHELL_READONLY:
            continue
        return True                                    # comando desconhecido → assume efeito (conservador)
    return False


@dataclass
class ToolContext:
    workspace: Path
    read_files: set[str] = field(default_factory=set)
    memory: object | None = None  # backend de memória (duck-typed: write/recall)
    skills: dict = field(default_factory=dict)  # nome -> corpo da SKILL.md (progressive disclosure)
    checkpoints: object | None = None  # snapshot antes de escrever → rollback (duck-typed: snapshot)
    spawn: object | None = None  # delega um subtask a um subagente isolado (Callable(goal, agent, model)->str)
    sandbox: object | None = None  # SandboxPolicy do run_shell (None → default_policy()); §P0 #2


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

    def to_openai_schema(self) -> dict:
        """Schema function-calling (OpenAI) desta tool — p/ tool-calls NATIVO (§3.5). O protocolo
        JSON-em-texto continua de pé; isto é a forma nativa equivalente, mesma `name`/args."""
        props = {k: {"type": "string", "description": v} for k, v in (self.args_schema or {}).items()}
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": props, "required": list(self.required)}}}


def openai_tools(registry: dict) -> list[dict]:
    """Schemas OpenAI das tools (p/ enviar no payload quando o provider faz function-calling nativo)."""
    return [t.to_openai_schema() for t in registry.values()]


def _safe_path(ctx: ToolContext, rel: str) -> Path:
    """Jail de workspace + bloqueio de symlink-escape (centralizado em core.file_safety)."""
    from okami.core.file_safety import safe_path
    return safe_path(ctx.workspace, rel)  # PathEscape é ValueError → callers `except ValueError` seguem


class ReadFile(Tool):
    name = "read_file"
    description = "Lê um arquivo de texto do workspace."
    args_schema = {"path": "caminho relativo ao workspace"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args["path"]
        from okami.core.file_safety import read_text_capped
        try:
            p = _safe_path(ctx, rel)
            text = read_text_capped(p)        # teto de tamanho → não estoura memória
        except FileNotFoundError:
            return ToolResult(False, f"arquivo não existe: {rel}")
        except Exception as e:  # noqa: BLE001 — inclui FileTooLarge/PathEscape (msg clara)
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
        from okami.core.file_safety import FileTooLarge, write_text_atomic
        try:
            n = write_text_atomic(p, content)   # atômico (sem arquivo meia-escrito) + teto de tamanho
        except FileTooLarge as e:
            return ToolResult(False, str(e))
        ctx.read_files.add(rel)  # acabou de escrever → conhece o conteúdo
        return ToolResult(True, f"escrito {rel} ({n} chars)", effect=True)


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
        from okami.core.file_safety import read_text_capped, write_text_atomic
        try:
            text = read_text_capped(p)
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
        write_text_atomic(p, new_text)        # escrita atômica (rede de segurança)
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


def _norm_name(s: str) -> str:
    """Normaliza p/ busca fuzzy: só alfanum, minúsculo (hífen/underscore/espaço/caso somem).
    'Okami-Agent' == 'okami_agent' == 'okamiagent'."""
    return "".join(c for c in s.lower() if c.isalnum())


class FindFiles(Tool):
    name = "find_files"
    description = ("Acha arquivos/pastas por nome no workspace — case-INSENSITIVE e fuzzy (acha "
                   "'okami-agent' mesmo a pasta sendo 'Okami-Agent'). Prefira a isto em vez de `find` "
                   "quando o nome pode variar em caso/hífen/underscore.")
    args_schema = {"query": "parte do nome (caso/hífen/underscore/espaço são ignorados)"}
    required = ("query",)
    _SKIP = {".git", "__pycache__", ".venv", "node_modules", ".okami", ".pytest_cache", "dist"}

    def run(self, args, ctx):
        q = _norm_name(args.get("query", ""))
        if not q:
            return ToolResult(False, "find_files exige 'query' não-vazio.")
        hits = []
        for p in ctx.workspace.rglob("*"):
            if any(part in self._SKIP for part in p.parts):
                continue
            if q in _norm_name(p.name):
                hits.append(str(p.relative_to(ctx.workspace)) + ("/" if p.is_dir() else ""))
                if len(hits) >= 60:
                    break
        return ToolResult(True, "\n".join(sorted(hits)) or f"(nada casou com '{args['query']}')", effect=False)


class RunShell(Tool):
    name = "run_shell"
    description = ("Executa um comando de shell no workspace, sob sandbox (timeout, teto de saída, env "
                   "sanitizado; isolamento real com backend docker). Em perfil read-only, comando que "
                   "altera estado é bloqueado.")
    args_schema = {"cmd": "comando a executar"}
    required = ("cmd",)

    def run(self, args, ctx):
        from okami.core.sandbox import default_policy, run_sandboxed
        cmd = args["cmd"]
        eff = shell_has_effect(cmd)   # read-only (ls/grep/cat…) → effect=False (não engana o watchdog)
        policy = ctx.sandbox or default_policy()
        mode = getattr(policy, "mode", "")
        if mode == "read-only" and eff:                          # defesa em profundidade (perfil)
            return ToolResult(False, f"sandbox read-only: comando que altera estado bloqueado ({cmd[:80]})",
                              effect=False)
        if mode != "yolo" and _SENSITIVE_PATH.search(cmd):       # P0.1: não deixa ler/exfiltrar segredo
            return ToolResult(False, "sandbox: comando toca caminho sensível (.env/.ssh/.aws/credenciais/"
                              f"*.pem/*.key) — bloqueado. Use o perfil yolo se for de propósito. ({cmd[:80]})",
                              effect=False)
        res = run_sandboxed(cmd, ctx.workspace, policy)
        return ToolResult(res.returncode == 0, f"exit={res.returncode}\n{res.output}", effect=eff)


class RememberFact(Tool):
    name = "remember"
    description = "Guarda um fato durável na memória de longo prazo (decisões, preferências, etc.)."
    args_schema = {"text": "o fato a lembrar"}
    required = ("text",)

    def run(self, args, ctx):
        if ctx.memory is None:
            return ToolResult(False, "memória não ativa")
        from okami.memory.policy import prepare
        item = prepare(args.get("text", ""), source="agent")   # classifica + barra efêmero/trivial
        if item is None:
            return ToolResult(True, "(contexto efêmero/trivial — não guardei na memória de longo prazo)",
                              effect=False)
        ctx.memory.write(item)
        return ToolResult(True, f"lembrado [{item.kind}]: {item.text[:80]}", effect=True)


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
        from okami.memory.citation import cited_line       # cada hit vem com [categoria · origem · confiança]
        return ToolResult(True, "\n".join(cited_line(i) for i in items))


class RememberUser(Tool):
    name = "remember_user"
    description = "Anota algo durável SOBRE O USUÁRIO em USER.md (preferência, contexto) — sempre no prompt."
    args_schema = {"text": "o fato sobre o usuário"}
    required = ("text",)

    def run(self, args, ctx):
        from okami.memory import files as _f
        if not _f.append_user(ctx.workspace, args["text"]):    # recusou (segredo) → não finge sucesso
            return ToolResult(True, "(não anotei — parece conter um segredo; não guardo isso no USER.md)",
                              effect=False)
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


class ProcessStart(Tool):
    name = "process_start"
    description = ("Roda um comando LONGO em BACKGROUND (não bloqueia o turno) → devolve um id. Use p/ "
                   "servidor que fica de pé, build/teste demorado, watch. Depois: process_poll/log/wait/kill.")
    args_schema = {"cmd": "comando a rodar em background",
                   "notify": "(opc) avisar no chat quando terminar (true/false)",
                   "watch": "(opc) lista de regex a vigiar no log (ex.: ['Listening on','ERROR'])",
                   "interactive": "(opc) PTY com stdin — use process_write p/ mandar input (true/false)"}
    required = ("cmd",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        from okami.core.sandbox import default_policy
        cmd = args["cmd"]
        policy = ctx.sandbox or default_policy()                 # #5: MESMA política do run_shell
        mode = getattr(policy, "mode", "")
        if mode == "read-only":                                  # processo longo é sempre efetivo → bloqueia
            return ToolResult(False, "sandbox read-only: process_start (comando longo) bloqueado.", effect=False)
        if mode != "yolo" and _SENSITIVE_PATH.search(cmd):       # P0.1: não exfiltra segredo nem em background
            return ToolResult(False, "sandbox: comando toca caminho sensível (.env/.ssh/.aws/credenciais/"
                              f"*.pem/*.key) — bloqueado. Use o perfil yolo se for de propósito. ({cmd[:80]})",
                              effect=False)
        watch = args.get("watch")
        if isinstance(watch, str):
            watch = [watch]
        try:
            meta = ProcessManager(ctx.workspace).start(
                cmd, policy, notify=bool(args.get("notify")), watch=watch,
                interactive=bool(args.get("interactive")))
        except ValueError as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao iniciar processo: {e}")
        tag = " · interativo (process_write)" if meta.get("interactive") else ""
        return ToolResult(True, f"processo {meta['id']} no ar (pid {meta['pid']}, backend {meta.get('backend')}){tag}: "
                          f"{cmd[:80]}", effect=True)


class ProcessWrite(Tool):
    name = "process_write"
    description = ("Manda input p/ o stdin de um processo INTERATIVO (process_start interactive=true). "
                   "`submit` (default true) acrescenta Enter. Depois leia com process_log/process_poll.")
    args_schema = {"id": "id do processo", "data": "texto a enviar",
                   "submit": "(opc) acrescenta Enter (default true)"}
    required = ("id", "data")

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        submit = args.get("submit", True)
        ok = ProcessManager(ctx.workspace).write(args["id"], str(args.get("data", "")),
                                                 submit=bool(submit) if submit is not None else True)
        return ToolResult(ok, "input enviado" if ok else "processo não é interativo / não existe / já terminou",
                          effect=ok)


class ProcessPoll(Tool):
    name = "process_poll"
    description = "Status de um processo em background (running/exited + exit code) + saída recente."
    args_schema = {"id": "id do processo (de process_start)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        st = pm.poll(args["id"])
        body = f"status={st.get('status')}"
        if st.get("status") == "exited":
            body += f" exit={st.get('exit_code')}"
        tail = pm.log(args["id"], tail=1500)
        return ToolResult(st.get("status") != "unknown", body + (f"\n{tail}" if tail else ""))


class ProcessWait(Tool):
    name = "process_wait"
    description = "Espera um processo em background terminar (até `timeout`s) e devolve o status final + saída."
    args_schema = {"id": "id do processo", "timeout": "(opc) segundos (default 30)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        try:
            to = float(args.get("timeout", 30))
        except (TypeError, ValueError):
            to = 30.0
        st = pm.wait(args["id"], timeout=to)
        return ToolResult(st.get("status") != "unknown",
                          f"status={st.get('status')} exit={st.get('exit_code')}\n{pm.log(args['id'], tail=2000)}")


class ProcessLog(Tool):
    name = "process_log"
    description = ("Saída (log) de um processo em background — redigida e truncada. Paginação opcional: "
                   "`offset`/`limit` por linha (offset<0 conta do fim) p/ navegar log grande.")
    args_schema = {"id": "id do processo", "offset": "(opc) linha inicial (negativo = do fim)",
                   "limit": "(opc) nº de linhas (default tail completo)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        if "offset" in args or "limit" in args:                  # modo paginado
            try:
                off, lim = int(args.get("offset", 0)), int(args.get("limit", 200))
            except (TypeError, ValueError):
                off, lim = 0, 200
            page = pm.log_page(args["id"], offset=off, limit=lim)
            head = f"[linhas {page['offset']}–{page['offset'] + page['shown']} de {page['total']}]\n"
            return ToolResult(True, head + ("\n".join(page["lines"]) or "(sem saída ainda)"))
        return ToolResult(True, pm.log(args["id"]) or "(sem saída ainda)")


class ProcessList(Tool):
    name = "process_list"
    description = "Lista os processos em background (id, status, exit code) — registry de processos."

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        procs = ProcessManager(ctx.workspace).list()
        if not procs:
            return ToolResult(True, "(nenhum processo em background)")
        rows = [f"{p['id']} · {p.get('status')}"
                + (f" exit={p.get('exit_code')}" if p.get("status") == "exited" else "")
                + f" · {str(p.get('cmd', ''))[:60]}" for p in procs]
        return ToolResult(True, "\n".join(rows))


class ProcessKill(Tool):
    name = "process_kill"
    description = "Mata um processo em background (SIGTERM no grupo)."
    args_schema = {"id": "id do processo"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        ok = ProcessManager(ctx.workspace).kill(args["id"])
        return ToolResult(ok, f"processo {args['id']} {'morto' if ok else 'não encontrado'}", effect=ok)


class ProcessSignal(Tool):
    name = "process_signal"
    description = ("Manda um sinal p/ um processo em background (lifecycle): TERM/INT/HUP/KILL/USR1/USR2/"
                  "CONT/STOP/QUIT. Ex.: HUP p/ recarregar, INT p/ Ctrl-C, USR1 p/ sinal custom.")
    args_schema = {"id": "id do processo", "signal": "nome do sinal (default TERM)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        name = str(args.get("signal", "TERM"))
        ok = ProcessManager(ctx.workspace).signal(args["id"], name)
        return ToolResult(ok, f"sinal {name.upper()} → {args['id']}" if ok
                          else f"falhou (sinal inválido / processo inexistente): {name}", effect=ok)


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
    tools = [Respond(), ReadFile(), WriteFile(), EditFile(), ListDir(), FindFiles(), RunShell(),
             ProcessStart(), ProcessPoll(), ProcessWait(), ProcessLog(), ProcessKill(), ProcessList(),
             ProcessWrite(), ProcessSignal(),
             RememberFact(), RecallMemory(), RememberUser(), UseSkill(), Spawn(), Browse(), GenerateImage(),
             FinishSetup(), TaskComplete(), TaskBlocked(), NeedInput()]
    return {t.name: t for t in tools}
