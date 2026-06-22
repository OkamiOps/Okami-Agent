"""Tools agênticas: use_skill, spawn (subagente), browse, generate_image."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult, _safe_path,
)


class UseSkill(Tool):
    name = "use_skill"
    description = ("Carrega o procedimento de uma skill do CATÁLOGO (siga-o à risca). Use quando a tarefa "
                   "casar com uma skill. Opcional `path`: lê um arquivo de apoio da skill sob demanda.")
    args_schema = {"name": "nome da skill no catálogo",
                   "path": "(opc) arquivo de apoio dentro da skill (references/…, scripts/…)"}
    required = ("name",)

    def run(self, args, ctx):
        name = args["name"]
        rel = str(args.get("path") or "").strip()
        if rel:                                       # tier-3: lê um arquivo DENTRO da skill sob demanda
            return self._read_file(name, rel, ctx)
        body = ctx.skills.get(name)
        if not body:
            disp = ", ".join(ctx.skills) or "(nenhuma)"
            return ToolResult(False, f"skill '{name}' não está no catálogo. Disponíveis: {disp}")
        root = getattr(ctx, "skills_dir", None)
        if root:                                     # LRU p/ o curator: registra que esta skill foi usada
            try:
                from okami.learning.curator import record_skill_use
                record_skill_use(root, name)
            except Exception:  # noqa: BLE001 — telemetria nunca derruba a tool
                pass
        try:                                          # #9: expande ${OKAMI_SKILL_DIR/SESSION_ID/DATE} (sem shell)
            from pathlib import Path as _P
            from okami.skills.preprocess import expand_skill_body
            body = expand_skill_body(body, skill_dir=str(_P(root) / name) if root else "")
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"SKILL '{name}' (siga este procedimento):\n{body}")

    def _read_file(self, name, rel, ctx):
        """Lê um arquivo de apoio DENTRO da skill (jailed na pasta da skill). Disclosure tier-3."""
        from pathlib import Path
        root = getattr(ctx, "skills_dir", None)
        if not root:
            return ToolResult(False, "leitura de arquivo de skill indisponível neste contexto (sem skills_dir).")
        skill_dir = Path(root) / name
        if not (skill_dir / "SKILL.md").exists():
            disp = ", ".join(ctx.skills) or "(nenhuma)"
            return ToolResult(False, f"skill '{name}' não está no catálogo. Disponíveis: {disp}")
        try:                                          # jail: o arquivo TEM que ficar dentro da skill
            from okami.core.file_safety import safe_path
            p = safe_path(skill_dir, rel, open_fs=False)
        except ValueError:
            return ToolResult(False, "path inválido: tem que ficar DENTRO da pasta da skill (sem escapar via ../).")
        if not p.exists() or not p.is_file():
            return ToolResult(False, f"arquivo '{rel}' não existe na skill '{name}'.")
        try:
            from okami.core.file_safety import read_text_capped
            content = read_text_capped(p)
        except OSError as e:
            return ToolResult(False, f"falha ao ler arquivo da skill: {e}")
        try:                                          # #9: ler subarquivo conta como VIEW (≠ use/patch)
            from okami.learning.curator import record_skill_use
            record_skill_use(root, name, kind="view")
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"SKILL '{name}' / {rel}:\n{content}")


class ManageSkill(Tool):
    name = "manage_skill"
    description = ("Cria/edita uma SKILL reutilizável (procedimento de uma CLASSE de tarefa). Quando você "
                   "descobrir um jeito durável de fazer uma classe de tarefa, GRAVE como skill. Nome no NÍVEL "
                   "DE CLASSE (kebab-case, ≤3 palavras): NUNCA a frase do pedido, nº de PR, string de erro ou "
                   "codinome. action=create|edit (corpo em markdown: ## Quando usar / ## Como / ## Cuidados), "
                   "write_file (adiciona script/referência à skill: path relativo + body), archive.")
    args_schema = {"action": "create|edit|write_file|archive", "name": "kebab-case curto (nível de classe)",
                   "description": "1 linha (≤120 chars)", "body": "markdown do procedimento, ou conteúdo do arquivo (write_file)",
                   "path": "write_file: caminho relativo dentro da skill (ex.: scripts/run.sh)"}
    required = ("action", "name")

    def run(self, args, ctx):
        import re as _re
        from pathlib import Path

        import yaml as _yaml

        from okami.skills.skill_security import Severity, scan_text
        root = getattr(ctx, "skills_dir", None)
        if not root:
            return ToolResult(False, "manage_skill indisponível neste contexto (sem skills_dir).")
        name = str(args.get("name", "")).strip().lower()
        if args.get("action") == "archive":          # arquiva (reversível) — usado pela consolidação
            from okami.learning.curator import _archive_skill
            return (ToolResult(True, f"skill '{name}' arquivada (.archive)", effect=True)
                    if _archive_skill(root, name) else ToolResult(False, f"skill '{name}' não encontrada."))
        if not _re.match(r"^[a-z0-9][a-z0-9._-]{1,47}$", name) or name.count("-") > 3:
            return ToolResult(False, "nome inválido: kebab-case curto (≤48 chars, ≤3 hífens), nível de CLASSE "
                              "(não a frase do pedido / PR / erro / codinome).")
        if args.get("action") == "write_file":           # adiciona script/referência à skill existente
            skill_dir = Path(root) / name
            if not (skill_dir / "SKILL.md").exists():
                return ToolResult(False, f"skill '{name}' não existe — crie com action=create primeiro.")
            rel = str(args.get("path", "")).strip()
            if not rel:
                return ToolResult(False, "write_file precisa de `path` (relativo dentro da skill).")
            try:                                          # jail: o arquivo TEM que cair dentro da skill
                from okami.core.file_safety import safe_path
                dst = safe_path(skill_dir, rel, open_fs=False)
            except ValueError:
                return ToolResult(False, "path inválido: tem que ficar DENTRO da pasta da skill (sem escapar).")
            content = str(args.get("body", ""))
            if any(f.severity >= Severity.HIGH for f in scan_text(rel, content)):
                return ToolResult(False, "arquivo bloqueado pelo scan de segurança (HIGH) — reescreva sem o padrão de risco.")
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8", newline="\n")
            except OSError as e:
                return ToolResult(False, f"falha ao gravar arquivo da skill: {e}")
            try:                                      # #9: editar/anexar conta como PATCH (sinal de manutenção)
                from okami.learning.curator import record_skill_use
                record_skill_use(root, name, kind="patch")
            except Exception:  # noqa: BLE001
                pass
            return ToolResult(True, f"arquivo '{rel}' gravado em skill '{name}'", effect=True)
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


class InstallSkill(Tool):
    name = "install_skill"
    description = ("INSTALA uma skill EXTERNA no catálogo a partir de uma fonte: owner/repo do GitHub, "
                   "caminho local, ou URL git. Baixa por git clone (NUNCA Docker nem `npx skills add` p/ "
                   "github/local), valida em quarentena (scan de segurança) e instala se a política "
                   "confiança×scan permitir (HIGH+ é bloqueado). Opcional `name`: instala só a skill com "
                   "esse nome de um repo com várias. Fontes clawhub:/npx exigem allow_exec=true (rodam "
                   "código antes do scan). Depois, use a skill com use_skill.")
    args_schema = {"source": "owner/repo (GitHub) | caminho local | URL git | clawhub:<slug>",
                   "name": "(opc) instalar só a skill com este nome (repo-biblioteca)",
                   "allow_exec": "(opc) true p/ permitir fonte que EXECUTA código no fetch (clawhub/npx)"}
    required = ("source",)

    def run(self, args, ctx):
        from okami.skills.install import install_from_source
        root = getattr(ctx, "skills_dir", None)
        if not root:
            return ToolResult(False, "install_skill indisponível neste contexto (sem skills_dir).")
        source = str(args.get("source") or "").strip()
        if not source:
            return ToolResult(False, "install_skill precisa de `source` (owner/repo, caminho local ou URL git).")
        lock_root = getattr(ctx, "workspace", None) or "."
        res = install_from_source(source, root, lock_root, only=str(args.get("name") or "").strip(),
                                  allow_exec=bool(args.get("allow_exec")))
        if not res.ok:
            return ToolResult(False, f"install_skill: {res.reason}")
        # injeta no catálogo EM MEMÓRIA → o agente pode use_skill já, sem reiniciar o gateway.
        if isinstance(getattr(ctx, "skills", None), dict):
            from okami.skills import parse_skill
            from pathlib import Path as _P
            for nm in res.installed:
                try:
                    ctx.skills[nm] = parse_skill(_P(root) / nm / "SKILL.md").body
                except OSError:
                    pass
        return ToolResult(True, f"skill(s) instalada(s): {', '.join(res.installed)} "
                          f"(fonte {res.kind}·confiança {res.trust}, scan {res.verdict}). "
                          "Carregue o procedimento com use_skill.", effect=True)


class Spawn(Tool):
    name = "spawn"
    description = ("Delega um SUBTASK a um subagente ISOLADO (contexto próprio) e recebe o resultado. "
                   "Use p/ paralelizar/especializar (ex.: 'agent: ui'). Para FAN-OUT, passe `tasks` (lista "
                   "de {goal, agent?, model?}) → roda N subagentes EM PARALELO e junta. Não abuse — tem custo.")
    args_schema = {"goal": "o subtask (1 só)", "agent": "(opcional) id do agente", "model": "(opcional) modelo",
                   "tasks": "(opcional) lista de {goal, agent?, model?} p/ rodar em PARALELO"}
    required = ()
    _MAX_PARALLEL = 6

    def run(self, args, ctx):
        if ctx.spawn is None:
            return ToolResult(False, "spawn indisponível neste contexto.")
        if args.get("tasks"):
            return self._parallel(args["tasks"], ctx)
        goal = args.get("goal")
        if not goal:
            return ToolResult(False, "spawn exige 'goal' (ou 'tasks' p/ fan-out paralelo).")
        try:
            out = ctx.spawn(goal, args.get("agent"), args.get("model"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"subagente falhou: {e}")
        return ToolResult(True, f"SUBAGENTE devolveu:\n{out}", effect=True)

    def _parallel(self, tasks, ctx):
        """Fan-out: roda os subtasks EM PARALELO (cap de concorrência) e junta os resultados rotulados.
        Um subtask que falha vira '(falhou: …)' sem derrubar os outros."""
        from concurrent.futures import ThreadPoolExecutor
        items = [t for t in tasks if isinstance(t, dict) and str(t.get("goal", "")).strip()]
        if not items:
            return ToolResult(False, "tasks vazio/sem goal — cada item precisa de {goal, agent?, model?}.")
        items = items[:self._MAX_PARALLEL]

        def _one(t):
            try:
                return t["goal"], str(ctx.spawn(t["goal"], t.get("agent"), t.get("model")))
            except Exception as e:  # noqa: BLE001 — falha de um não derruba o fan-out
                return t["goal"], f"(falhou: {e})"
        with ThreadPoolExecutor(max_workers=min(self._MAX_PARALLEL, len(items))) as ex:
            results = list(ex.map(_one, items))
        blocks = [f"### subagente {i + 1} — {g}\n{out}" for i, (g, out) in enumerate(results)]
        return ToolResult(True, "SUBAGENTES (paralelo) devolveram:\n\n" + "\n\n".join(blocks), effect=True)


class Browse(Tool):
    name = "browse"
    description = ("Abre uma URL e lê o texto. Com Playwright também: action=snapshot|click|fill|screenshot. "
                   "snapshot numera os elementos interativos como [N] (mapa de acessibilidade); depois "
                   "click/fill aceitam esse [N] como selector (resolvido por papel+nome) — bem mais "
                   "confiável que adivinhar CSS. Mantém sessão LOGADA entre chamadas (perfil persistente).")
    args_schema = {"url": "URL", "action": "read|snapshot|click|fill|screenshot",
                   "selector": "(opc) ref [N] de uma snapshot OU seletor CSS de fallback",
                   "text": "(opc) texto p/ fill"}
    required = ("url",)

    def run(self, args, ctx):
        try:
            from okami.integrations.browser import browse
            out = browse(args["url"], args.get("action", "read"), args.get("selector"), args.get("text"),
                         args.get("screenshot"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"browse falhou: {e}")
        from okami.core.tools.base import untrusted_wrap   # página externa = dado, não instrução
        return ToolResult(True, untrusted_wrap("browse", out),
                          effect=args.get("action") in ("click", "fill"))


class GenerateImage(Tool):
    name = "generate_image"
    description = ("Gera uma IMAGEM (gpt-image-2 via assinatura Codex). Sem 'references' = imagem nova; "
                   "com 'references' (caminhos no workspace) = MANDA essas imagens + o prompt p/ o modelo "
                   "transformar (ex.: virar infográfico) — NÃO edite o arquivo você mesmo.")
    args_schema = {"prompt": "o que gerar", "path": "saída (.png)", "references": "(opc) lista de imagens base"}
    required = ("prompt", "path")

    def check(self):
        """Depende da assinatura Codex — sem login, a tool sai do registro (check_fn, item 27)."""
        from okami.llm import oauth
        if not oauth.codex_access_token():
            return "sem login Codex (rode: okami login codex)"
        return None

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
