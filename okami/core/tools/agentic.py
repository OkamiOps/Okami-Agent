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
                   "de {goal, agent?, model?}) → roda N subagentes EM PARALELO e junta. Para tarefa LONGA "
                   "que NÃO precisa do resultado no MESMO turno, passe background=true → roda em SEGUNDO "
                   "PLANO e avisa o dono quando terminar (NÃO trava o chat). Não abuse — tem custo.")
    args_schema = {"goal": "o subtask (1 só)", "agent": "(opcional) id do agente", "model": "(opcional) modelo",
                   "tasks": "(opcional) lista de {goal, agent?, model?} p/ rodar em PARALELO",
                   "background": "(opcional) true = roda em segundo plano e avisa quando terminar (tarefa longa)"}
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
        if args.get("background"):
            return self._background(goal, args.get("agent"), args.get("model"), ctx)
        try:
            out = ctx.spawn(goal, args.get("agent"), args.get("model"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"subagente falhou: {e}")
        return ToolResult(True, f"SUBAGENTE devolveu:\n{out}", effect=True)

    def _background(self, goal, agent, model, ctx):
        """Roda o subagente em SEGUNDO PLANO (thread daemon) e retorna NA HORA — não trava o turno do pai.
        Cap de concorrência (Semaphore): fila cheia → roda SÍNCRONO inline (não perde). Resultado persiste
        em .okami/spawn/<id>.json (estado running→done/failed); ao terminar avisa o dono no chat que PEDIU
        (ctx.notify capturado → chat certo mesmo após o turno) e o agente LÊ de volta com `spawn_jobs`."""
        import threading

        from okami.core.spawn_jobs import (
            acquire_slot, new_job_id, prune_spawn_jobs, release_slot, run_spawn_job,
        )
        ws = getattr(ctx, "workspace", ".")
        if not acquire_slot():                         # fila de background cheia → não estoura threads
            try:
                out = ctx.spawn(goal, agent, model)
            except Exception as e:  # noqa: BLE001
                return ToolResult(False, f"subagente falhou: {e}")
            return ToolResult(True, f"(fila de background cheia — rodei INLINE) SUBAGENTE devolveu:\n{out}",
                              effect=True)
        try:
            prune_spawn_jobs(ws)                        # GC oportunista ao abrir um novo job
        except Exception:  # noqa: BLE001
            pass
        job = new_job_id()
        notify, spawn_fn = getattr(ctx, "notify", None), ctx.spawn

        def _target():
            try:
                run_spawn_job(job, goal, agent, model, spawn_fn, notify, ws)
            finally:
                release_slot()
        t = threading.Thread(target=_target, daemon=True)
        t.start()
        self._last_bg_thread = t                       # referência só p/ o teste poder .join()
        return ToolResult(True, f"▶ subagente {job} rodando em SEGUNDO PLANO — te aviso aqui quando "
                          f"terminar. Veja/use o resultado com `spawn_jobs result {job}` "
                          f"(ou .okami/spawn/{job}.json).", effect=True)

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


class SpawnJobs(Tool):
    name = "spawn_jobs"
    description = ("Inspeciona/usa subagentes em SEGUNDO PLANO (lançados com spawn background=true). "
                   "action=list (recentes + estado) | status (job → running/done/failed) | result (job → "
                   "pega a saída quando terminou) | await (job → espera ATÉ Ns o resultado NESTE turno). "
                   "Use result/await p/ ENCADEAR: spawn longo agora → usar a saída depois (ou no mesmo turno).")
    args_schema = {"action": "list | status | result | await", "job": "(status/result/await) id do job (8 hex)",
                   "timeout": "(await) segundos a esperar (default 60, máx 300)"}
    required = ("action",)

    def run(self, args, ctx):
        from okami.core.spawn_jobs import await_job, list_jobs, read_job
        ws = getattr(ctx, "workspace", ".")
        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            jobs = list_jobs(ws)
            if not jobs:
                return ToolResult(True, "(nenhum subagente em segundo plano)")
            return ToolResult(True, "subagentes em segundo plano:\n" + "\n".join(
                f"- {j['job']} · {j['state']} · {str(j['goal'])[:60]}" for j in jobs))
        job = str(args.get("job") or "").strip()
        if action == "await":
            try:
                timeout = float(args.get("timeout") or 60)
            except (TypeError, ValueError):
                timeout = 60.0
            rec = await_job(ws, job, timeout)
        elif action in ("status", "result"):
            rec = read_job(ws, job)
        else:
            return ToolResult(False, "action inválida: use list | status | result | await.")
        if rec is None:
            return ToolResult(False, f"job '{job}' não encontrado (use action=list).")
        state = rec.get("state", "?")
        # header AUTOCONTIDO (ideia do Hermes): o pai pode ter esquecido por que o subagente existia.
        header = f"[subagente {rec.get('job', job)} · objetivo: {str(rec.get('goal', ''))[:80]} · estado: {state}]"
        if state == "running":
            return ToolResult(True, header + " — ainda rodando; use action=await p/ esperar.")
        if action == "status":
            return ToolResult(True, header)
        return ToolResult(True, f"{header}\n{rec.get('result', '')}")


def _has_playwright() -> bool:
    """Playwright instalado? (gate p/ as ações interativas do browse — read não precisa)."""
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


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
        action = args.get("action", "read")
        # action≠read precisa do Playwright. Sem ele, browse() degrada SILENCIOSO p/ fetch (texto) — o
        # agente pediria 'screenshot' e receberia texto achando que deu certo. Falha CLARO em vez disso.
        if action != "read" and not _has_playwright():
            return ToolResult(False, f"a ação '{action}' do browse precisa do Playwright (não instalado). "
                              "Rode: pip install playwright && playwright install chromium. "
                              "Sem ele, só action=read funciona (lê o texto da página).")
        try:
            from okami.integrations.browser import browse
            out = browse(args["url"], action, args.get("selector"), args.get("text"),
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
