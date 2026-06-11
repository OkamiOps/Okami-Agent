"""Tools de arquivo + shell: read/write/edit/list/find + run_shell."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult, _SENSITIVE_PATH, _safe_path, shell_has_effect,
)


def _as_int(v) -> int | None:
    """Aceita int ou string numérica (o modelo às vezes manda "5"); senão None."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class ReadFile(Tool):
    name = "read_file"
    description = ("Lê um arquivo de texto do workspace. Opcional: offset (pular N linhas) + limit "
                   "(ler só N linhas) p/ paginar arquivo/saída grande sem trazer tudo de uma vez.")
    args_schema = {"path": "caminho relativo ao workspace",
                   "offset": "(opcional) nº de linhas a pular do início",
                   "limit": "(opcional) máx. de linhas a retornar"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "read_file: 'path' precisa ser uma string não-vazia.", effect=False)
        mode = getattr(ctx.sandbox, "mode", "")          # simetria com run_shell: read_file NÃO pode ser a
        if mode != "yolo" and _SENSITIVE_PATH.search(rel):  # porta dos fundos p/ exfiltrar segredo
            return ToolResult(False, "sandbox: arquivo sensível (.env/.ssh/.aws/credenciais/*.pem/*.key) — "
                              f"bloqueado p/ não vazar segredo. Use o perfil yolo se for de propósito. ({rel})",
                              effect=False)
        from okami.core.file_safety import read_text_capped
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        # erros ACIONÁVEIS (anti-thrash): o modelo chutava caminho e levava OSError cru → re-tentava sem fim.
        if p.is_dir():
            return ToolResult(False, f"'{rel}' é um DIRETÓRIO, não um arquivo — use list_dir('{rel}') p/ ver "
                              "o conteúdo (read_file é só p/ arquivo).", effect=False)
        if not p.exists():
            return ToolResult(False, f"arquivo não existe: {rel} — NÃO chute o caminho; use list_dir p/ navegar "
                              "ou find_files p/ achar pelo nome.", effect=False)
        try:
            text = read_text_capped(p)        # teto de tamanho → não estoura memória
        except Exception as e:  # noqa: BLE001 — inclui FileTooLarge (msg clara)
            return ToolResult(False, f"erro ao ler {rel}: {e}", effect=False)
        ctx.read_files.add(rel)
        # PAGINAÇÃO (offset/limit por LINHA): recupera o resto de uma saída grande persistida sem
        # trazer o arquivo inteiro. Sem offset/limit → arquivo inteiro (back-compat).
        off = _as_int(args.get("offset"))
        lim = _as_int(args.get("limit"))
        if off is None and lim is None:
            return ToolResult(True, text, effect=False)
        lines = text.splitlines()
        start = max(0, off or 0)
        if start >= len(lines) and lines:
            return ToolResult(True, f"(offset {start} além do fim — o arquivo tem {len(lines)} linha(s))",
                              effect=False)
        end = start + lim if lim is not None else len(lines)
        chunk = "\n".join(lines[start:end])
        remaining = len(lines) - end
        if remaining > 0:
            chunk += f"\n\n[… +{remaining} linha(s); continue com offset={end} …]"
        return ToolResult(True, chunk, effect=False)


class WriteFile(Tool):
    name = "write_file"
    description = "Escreve/sobrescreve um arquivo. Para sobrescrever um existente, leia-o antes (grounding)."
    args_schema = {"path": "caminho relativo", "content": "conteúdo completo do arquivo"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:           # path None/tipo-errado → erro limpo (não TypeError)
            return ToolResult(False, "write_file: 'path' precisa ser uma string não-vazia.")
        content = args.get("content", "")
        if not isinstance(content, str):                  # None/bytes/num → coage p/ texto (não crasha o .encode)
            content = "" if content is None else str(content)
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
        # Grounding anti-alucinação (§3.7), igual ao write_file: não edita às cegas um arquivo não-lido
        # (um 'old' adivinhado não basta). prelearned_files do harness já entram em ctx.read_files (exceção).
        if rel not in ctx.read_files:
            return ToolResult(False, f"'{rel}' existe mas você não o leu — use read_file antes de "
                                     "editar (grounding; edição cega por trecho adivinhado é recusada).")
        from okami.core.file_safety import MAX_WRITE_BYTES, read_text_capped, write_text_atomic
        try:
            # P1 do audit 2026-06-07: EditFile usava MAX_READ_BYTES (5MB) e quebrava com
            # mensagem confusa ("use run_shell p/ fatiar") mesmo quando o `old` cabia nos
            # primeiros MB. Agora usa o mesmo teto da escrita (10MB) — o `old` que cabe em
            # 10MB é editável; o que não cabe, retorna erro claro com o limite.
            text = read_text_capped(p, limit=MAX_WRITE_BYTES)
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
        raw = args.get("query")
        q = _norm_name(raw if isinstance(raw, str) else ("" if raw is None else str(raw)))
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
                   "altera estado é bloqueado. Comando demorado: passe timeout=N (máx 1800s) ou, p/ algo "
                   "realmente longo (servidor/build), use process_start (background, sem teto).")
    args_schema = {"cmd": "comando a executar",
                   "timeout": "(opc) segundos até cortar o comando — default 120, máx 1800"}
    required = ("cmd",)
    _MAX_TIMEOUT = 1800           # 30min de teto p/ UM comando — acima disso é trabalho de background (process_start)

    def run(self, args, ctx):
        import dataclasses
        from okami.core.sandbox import default_policy, run_sandboxed
        cmd = args.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():   # modelo fraco manda {"cmd": null/123/[…]} → erro LIMPO
            return ToolResult(False, "run_shell: 'cmd' precisa ser uma string não-vazia.", effect=False)
        eff = shell_has_effect(cmd)   # read-only (ls/grep/cat…) → effect=False (não engana o watchdog)
        policy = ctx.sandbox or default_policy()
        # timeout POR-CHAMADA: comando sabidamente demorado (teste/build grande, transformar arquivo enorme)
        # pode pedir mais tempo sem mexer no default global. Clamp p/ não virar "trava pra sempre".
        to = args.get("timeout")
        if to is not None:
            try:
                policy = dataclasses.replace(policy, timeout=max(1, min(int(to), self._MAX_TIMEOUT)))
            except (TypeError, ValueError):
                pass                                              # timeout inválido → ignora, usa o da policy
        mode = getattr(policy, "mode", "")
        from okami.core import approval as _ap
        _hl = _ap.detect_hardline(cmd)
        if _hl:                                                  # HARDLINE (Hermes): bloqueio INCONDICIONAL —
            return ToolResult(False, f"🛑 BLOQUEADO (hardline): {_hl}. Comando catastrófico sem uso "  # nem /yolo passa
                              f"legítimo — recusado em QUALQUER modo. ({cmd[:80]})", effect=False)
        if mode == "read-only" and eff:                          # defesa em profundidade (perfil)
            return ToolResult(False, f"sandbox read-only: comando que altera estado bloqueado ({cmd[:80]})",
                              effect=False)
        if mode != "yolo" and _SENSITIVE_PATH.search(cmd):       # P0.1: não deixa ler/exfiltrar segredo
            return ToolResult(False, "sandbox: comando toca caminho sensível (.env/.ssh/.aws/credenciais/"
                              f"*.pem/*.key) — bloqueado. Use o perfil yolo se for de propósito. ({cmd[:80]})",
                              effect=False)
        res = run_sandboxed(cmd, ctx.workspace, policy)
        from okami.core.redact import redact            # token impresso na saída (gh auth/build log) NÃO pode
        out = f"exit={res.returncode}\n{redact(res.output)}"   # ir verbatim p/ o LLM/transcript (igual ao bg log)
        if getattr(res, "timed_out", False):                     # cortou no teto → ensina a recuperar (não é "falha real")
            out += (f"\n[o comando passou de {policy.timeout}s e foi cortado. Se é legítimo e demora mesmo: "
                    f"rode de novo com timeout=N (máx {self._MAX_TIMEOUT}), ou use process_start p/ rodar "
                    "em background sem teto e acompanhar com process_poll/process_log.]")
        return ToolResult(res.returncode == 0, out, effect=eff)
