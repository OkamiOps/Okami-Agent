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
        from pathlib import Path as _P
        skill_dir = str((_P(root) / name).resolve()) if root else ""   # FORA do try: o path NÃO depende do
        try:                                          # expand (se o import falhar, ainda damos o caminho abs)
            from okami.skills.preprocess import expand_skill_body   # #9: expande ${OKAMI_SKILL_DIR/...} sem shell
            body = expand_skill_body(body, skill_dir=skill_dir)
        except Exception:  # noqa: BLE001 — expansão é opcional; nunca apaga o skill_dir
            pass
        loc = (f"\n\n[arquivos desta skill em: {skill_dir} — run_shell roda no WORKSPACE, então use o caminho "
               f"ABSOLUTO p/ os scripts (ex.: `node {skill_dir}/scripts/run.js`) ou `cd` p/ lá primeiro]") if skill_dir else ""
        files_note = self._support_files_note(name, skill_dir)   # tier-3 confiável: LISTA os arquivos de apoio
        return ToolResult(True, f"SKILL '{name}' (siga este procedimento):\n{body}{loc}{files_note}")

    @staticmethod
    def _support_files_note(name: str, skill_dir: str) -> str:
        """Enumera os arquivos de apoio da skill (references/scripts/templates/assets) — sem isto o modelo
        ADIVINHA o path no tier-3. Bounded; vazio se não há nenhum. Paridade Hermes (linked_files)."""
        if not skill_dir:
            return ""
        try:
            from pathlib import Path as _P
            sd = _P(skill_dir)
            rels: list[str] = []
            extra = 0                                  # arquivos ALÉM dos 30 listados (p/ avisar '+N mais')
            for sub in ("references", "scripts", "templates", "assets"):
                d = sd / sub
                if not d.is_dir():
                    continue
                for f in sorted(d.rglob("*")):
                    if not f.is_file():
                        continue
                    if len(rels) < 30:
                        rels.append(str(f.relative_to(sd)))
                    else:
                        extra += 1                     # não despeja tudo, mas CONTA (senão o modelo acha que
                if extra > 500:                        # a lista é completa e perde um arquivo crítico)
                    break
            if not rels:
                return ""
            more = f" … (+{extra} arquivo(s) — abra com use_skill(path=))" if extra else ""
            return (f'\n\n[arquivos de apoio desta skill (carregue sob demanda com '
                    f'use_skill(name="{name}", path="<arquivo>")): ' + ", ".join(rels) + more + "]")
        except Exception:  # noqa: BLE001 — enumeração nunca derruba a tool
            return ""

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
    arg_constraints = {"action": {"enum": ["create", "edit", "write_file", "archive"]}}

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
                   "allow_exec": "(opc) true p/ permitir fonte que EXECUTA código no fetch (clawhub/npx)",
                   "confirm": "(opc) true p/ confirmar fonte não-confiável (community/unverified)"}
    required = ("source",)

    def run(self, args, ctx):
        from okami.skills.install import install_from_source
        root = getattr(ctx, "skills_dir", None)
        if not root:
            return ToolResult(False, "install_skill indisponível neste contexto (sem skills_dir).")
        source = str(args.get("source") or "").strip()
        if not source:
            return ToolResult(False, "install_skill precisa de `source` (owner/repo, caminho local ou URL git).")
        # ANTI-LOOP (paridade Hermes — install fora do hot loop): a MESMA fonte que JÁ falhou nesta sessão
        # NÃO é re-tentada. O fetch (git/npx) lento ou quebrado virava loop de ~59min; falhou 1x → pare.
        try:
            tried = ctx.__dict__.setdefault("_failed_skill_installs", set())
        except Exception:  # noqa: BLE001 — ctx exótico (slots): segue sem o cap, não quebra
            tried = set()
        if source in tried:
            return ToolResult(False, f"'{source}' JÁ falhou nesta sessão — NÃO re-tente a mesma fonte. "
                              "Tente uma fonte diferente, ou peça ao dono a fonte/credencial certa.")
        lock_root = getattr(ctx, "workspace", None) or "."
        res = install_from_source(source, root, lock_root, only=str(args.get("name") or "").strip(),
                                  allow_exec=bool(args.get("allow_exec")), confirm=bool(args.get("confirm")))
        if not res.ok:
            tried.add(source)                              # marca a fonte como falha → não re-tenta
            return ToolResult(False, f"install_skill: {res.reason}")
        # injeta no catálogo EM MEMÓRIA → o agente pode use_skill já, sem reiniciar o gateway.
        skills_cat = getattr(ctx, "skills", None)
        failed: list[str] = []
        if isinstance(skills_cat, dict):
            from okami.skills import parse_skill
            from pathlib import Path as _P
            for nm in res.installed:
                try:
                    skills_cat[nm] = parse_skill(_P(root) / nm / "SKILL.md").body
                except Exception as e:  # noqa: BLE001 — inclui UnicodeDecodeError (NÃO é OSError): não crasha
                    failed.append(nm)
                    from okami import log
                    log.warn(f"install_skill: '{nm}' instalada em disco mas NÃO injetada no catálogo ({e}).")
        dep_note = ("\n⚠ ANTES de usar, instale as deps externas (run_shell): " + "; ".join(res.deps)) if res.deps else ""
        warn = (f"\n⚠ {', '.join(failed)} ficou INVISÍVEL no catálogo (erro de leitura/parse) — reinstale ou "
                "reinicie o gateway antes de use_skill") if failed else ""
        # effect=True SÓ se nada falhou na injeção (catálogo em memória): senão o watchdog acha que houve
        # progresso real mas use_skill vai falhar p/ a skill não-injetada → mini-loop de re-instalação.
        full = (not failed) or not isinstance(skills_cat, dict)
        return ToolResult(True, f"skill(s) instalada(s): {', '.join(res.installed)} "
                          f"(fonte {res.kind}·confiança {res.trust}, scan {res.verdict}). "
                          f"Carregue o procedimento com use_skill.{dep_note}{warn}", effect=full)


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
    # sem arg_types o rail nativo manda "false" (string) e bool("false") é True (bug) — mesmo caso do
    # replace_all em files.py.
    arg_types = {"background": "boolean"}
    arg_constraints = {"background": {"default": False}}
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
    arg_types = {"timeout": "integer"}
    # enum trava o domínio (auditoria 2026-07) — sem isto o modelo chuta "check"/"get" em vez de status/result.
    arg_constraints = {
        "action": {"enum": ["list", "status", "result", "await"]},
        "timeout": {"default": 60, "minimum": 1, "maximum": 300},
    }

    def run(self, args, ctx):
        from okami.core.spawn_jobs import await_job, list_jobs, read_job
        ws = getattr(ctx, "workspace", ".")
        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            jobs = list_jobs(ws)
            if not jobs:
                return ToolResult(True, "(nenhum subagente em segundo plano)")
            def _line(j):
                prog = f" · passo {j['step']} ({j['tool']})" if j.get("state") == "running" and j.get("step") else ""
                return f"- {j['job']} · {j['state']}{prog} · {str(j['goal'])[:60]}"
            return ToolResult(True, "subagentes em segundo plano:\n" + "\n".join(_line(j) for j in jobs))
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
            prog = f" · passo {rec['step']} ({rec.get('tool', '')})" if rec.get("step") else ""
            return ToolResult(True, header[:-1] + prog + "] — ainda rodando; use action=await p/ esperar.")
        if action == "status":
            return ToolResult(True, header)
        return ToolResult(True, f"{header}\n{rec.get('result', '')}")


def _has_playwright() -> bool:
    """Playwright instalado? (gate p/ as ações interativas do browse — read não precisa)."""
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


_BROWSE_ACTIONS = ("read", "open", "snapshot", "click", "fill", "screenshot", "scroll", "back",
                   "press", "eval", "close_session")
_BROWSE_EFFECT_ACTIONS = frozenset({"click", "fill", "press", "eval", "back"})


class Browse(Tool):
    name = "browse"
    description = ("Abre uma URL e interage com a página, mantendo a MESMA sessão (Chromium+cookies) "
                   "entre chamadas — login → navega → clica sem perder estado. `url` é OBRIGATÓRIO só na "
                   "1ª chamada da sessão; depois, omita p/ agir na página ATUAL. action=read|open|"
                   "snapshot|click|fill|screenshot|scroll|back|press|eval|close_session. snapshot numera "
                   "os elementos interativos como [N] (mapa de acessibilidade); click/fill aceitam esse "
                   "[N] como `selector` (resolvido por papel+nome) — bem mais confiável que adivinhar CSS. "
                   "screenshot devolve a IMAGEM (você VÊ a tela). eval roda JS na página (BLOQUEADO p/ "
                   "document.cookie/localStorage/fetch a endereço privado — não tenta ler sessão/exfiltrar). "
                   "scroll usa `text` como pixels (default 800); press usa `text` como tecla (ex.: 'Enter'). "
                   "close_session encerra a sessão e libera o Chromium. Dialog (alert/confirm) da página é "
                   "auto-DISMISSADO por padrão — não trava a chamada.")
    args_schema = {"url": "(obrigatório só na 1ª chamada da sessão) URL",
                   "action": "read|open|snapshot|click|fill|screenshot|scroll|back|press|eval|close_session",
                   "selector": "(opc) ref [N] de uma snapshot OU seletor CSS de fallback",
                   "text": "(opc) texto p/ fill; tecla p/ press; pixels p/ scroll; código JS p/ eval",
                   "screenshot": "(action=screenshot) caminho de saída .png no workspace",
                   "session_id": "(opc) identificador da sessão de browser — default deriva da conversa atual"}
    required = ()
    arg_constraints = {"action": {"enum": list(_BROWSE_ACTIONS), "default": "read"}}

    def run(self, args, ctx):
        action = args.get("action") or "read"
        if action not in _BROWSE_ACTIONS:
            return ToolResult(False, f"browse: action inválida '{action}'. Use: {', '.join(_BROWSE_ACTIONS)}.")
        session_id = str(args.get("session_id") or getattr(ctx, "chat_id", "") or "default")

        if action == "close_session":
            from okami.integrations.browser_session import SESSIONS
            closed = SESSIONS.close(session_id)
            msg = (f"sessão de browser '{session_id}' encerrada." if closed
                  else f"sessão de browser '{session_id}' não estava ativa.")
            return ToolResult(True, msg, effect=closed)

        # action≠read/open precisa do Playwright. Sem ele, browse() degrada SILENCIOSO p/ fetch (texto) — o
        # agente pediria 'screenshot' e receberia texto achando que deu certo. Falha CLARO em vez disso.
        if action not in ("read", "open") and not _has_playwright():
            return ToolResult(False, f"a ação '{action}' do browse precisa do Playwright (não instalado). "
                              "Rode: pip install playwright && playwright install chromium. "
                              "Sem ele, só action=read/open funciona (lê o texto da página).")

        url = args.get("url") or None
        shot_path: str | None = None
        if action == "screenshot":
            try:
                shot_path = str(_safe_path(ctx, args.get("screenshot") or "screenshot.png"))
            except ValueError as e:
                return ToolResult(False, str(e))

        try:
            from okami.integrations.browser import browse
            out = browse(url, action, args.get("selector"), args.get("text"), shot_path,
                        session_id=session_id)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"browse falhou: {e}")

        from okami.core.tools.base import untrusted_wrap   # página externa = dado, não instrução
        content = None
        if action == "screenshot" and shot_path and "salvo" in out:
            from okami.core.tools.image_block import image_block
            content = image_block(shot_path)
        return ToolResult(True, untrusted_wrap("browse", out),
                          effect=action in _BROWSE_EFFECT_ACTIONS, content=content)


class GenerateImage(Tool):
    name = "generate_image"
    description = ("Gera uma IMAGEM (gpt-image-2 via assinatura Codex). Sem 'references' = imagem nova; "
                   "com 'references' (caminhos no workspace) = MANDA essas imagens + o prompt p/ o modelo "
                   "transformar (ex.: virar infográfico) — NÃO edite o arquivo você mesmo.")
    args_schema = {"prompt": "o que gerar", "path": "saída (.png)", "references": "(opc) lista de imagens base"}
    required = ("prompt", "path")

    def check(self):
        """Precisa da assinatura Codex OU de um backend de fallback configurado (media.image).
        Sem nenhum dos dois, a tool sai do registro (check_fn, item 27)."""
        from okami.llm import oauth
        if oauth.codex_access_token():
            return None
        try:
            from okami.llm.imagegen import image_config
            from okami.config import load_config
            if image_config(load_config()):
                return None
        except Exception:  # noqa: BLE001 — sem config de fallback resolvível → cai no aviso abaixo
            pass
        return "sem login Codex (rode: okami login codex) nem backend de imagem em media.image"

    def run(self, args, ctx):
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():   # modelo fraco manda {"prompt": null} → erro LIMPO
            return ToolResult(False, "generate_image: 'prompt' precisa ser uma string não-vazia.", effect=False)
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            return ToolResult(False, "generate_image: 'path' precisa ser uma string não-vazia.", effect=False)
        try:
            p = _safe_path(ctx, args["path"])
            refs = []
            for r in (args.get("references") or []):
                refs.append(str(_safe_path(ctx, r)))      # referências também dentro do workspace
        except ValueError as e:
            return ToolResult(False, str(e))
        try:
            from okami.llm.imagegen import generate_image
            generate_image(prompt, str(p), references=refs or None)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao gerar imagem: {e}")
        how = f" (com {len(refs)} referência(s))" if refs else ""
        return ToolResult(True, f"imagem gerada{how}: {args['path']}", effect=True)
