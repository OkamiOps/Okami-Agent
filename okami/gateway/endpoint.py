"""AgentEndpoint + Session — control plane por agente (§13): um canal → sessões por chat → tarefa.

Robustez: histórico por sessão, slash commands (/new /reset /status /stop /yolo /help /model /compact…),
concorrência (uma tarefa por sessão), go/no-go por chat (timeout fail-closed), /stop que CANCELA de
verdade (callback no harness), gênese/onboarding no primeiro contato.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable

from okami.gateway.endpoint_commands import EndpointCommandsMixin
from okami.gateway.genesis import GENESIS_BLOCK, _history_block, genesis_pending
from okami.gateway.sessions import TranscriptStore


class Session:
    """Estado de uma conversa (um chat × um agente)."""

    def __init__(self):
        self.history: list[tuple[str, str]] = []
        self.busy = False
        self.yolo = False
        self.cancel = False
        self.persona_overlay = ""        # persona TEMPORÁRIA da sessão (/persona) — não grava
        self.resume_attempts = 0         # guarda anti-loop de auto-resume (Hermes #7536)
        self.reasoning_effort = ""       # esforço de raciocínio desta sessão (/think) — vence o default
        self.model_override = ""         # modelo desta sessão (/model <id>) — vence o default
        self.title = ""                  # nome amigável da conversa (/title) — aparece no /status e /sessions
        self.voice_off = False           # /voice off → não responde em áudio (TTS) nesta sessão
        self.busy_mode = "queue"         # ocupado + nova msg: queue (fila) | interrupt (corta a atual)
        self.queued: list = []           # mensagens em fila (runtime; não persiste)

    def interrupted(self) -> bool:
        """Tarefa interrompida = histórico termina numa fala do USER sem resposta do AGENTE."""
        return bool(self.history) and self.history[-1][0] == "USER"


class AgentEndpoint(EndpointCommandsMixin):
    """Liga um agente ao seu canal; gerencia sessões por chat."""

    def __init__(self, agent_id: str, cfg, ws, channel, run_task: Callable,
                 approval_mode: str = "manual", approval_timeout: float = 120.0,
                 max_history_chars: int = 6000, stt=None, tts=None, spawn: Callable | None = None,
                 auto_resume: bool = False, max_sessions: int = 500, on_event: Callable | None = None,
                 reactions: bool = False):
        self.on_event = on_event             # progresso ao vivo (tool-calls/loop/compact) — chat liga, Telegram não
        self.agent_id = agent_id
        self.cfg = cfg
        self.ws = ws
        self.channel = channel
        from okami.core.tool_policy import surface_of
        self.surface = surface_of(channel)   # CLI/telegram/group/paperclip → tool policy por superfície (P1.4)
        self.run_task = run_task
        self.stt = stt
        self.tts = tts
        self.approval_mode = approval_mode
        self.approval_timeout = approval_timeout
        self.max_history_chars = max_history_chars
        self.auto_resume = auto_resume       # retomar tarefa interrompida no boot (com guarda anti-loop)
        self.max_sessions = max_sessions
        self.store = TranscriptStore(ws)     # 2 camadas: metadados + transcript append-only (§13)
        from okami.gateway.approvals import ApprovalStore
        self.approvals = ApprovalStore(ws)   # aprovação como objeto persistente single-use (#7)
        self.sessions: dict[str, Session] = {}
        self._pending: dict[str, queue.Queue] = {}
        self._img: dict[str, str] = {}       # imagem pendente por chat (vision §6)
        from collections import OrderedDict
        self._seen_msgs: OrderedDict = OrderedDict()   # idempotência por turno (#3): msg_id já processado
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._bg: dict[int, str] = {}        # tarefas /background em andamento (id → resumo) — não bloqueia a sessão
        self._bg_cancel: dict[int, threading.Event] = {}   # /background cancel <id> → sinaliza a thread (cooperativo)
        from okami.gateway.background import BackgroundRegistry
        self._bgreg = BackgroundRegistry(ws)   # registro PERSISTIDO (sobrevive a restart) das tarefas /background
        self.reactions = reactions           # reações 👀/👍/👎 na mensagem (Telegram) — opt-in
        self._last_msg_id: dict[str, str] = {}   # última msg_id por chat → alvo da reação
        self.running = True

    def session(self, chat_id) -> Session:
        """Sessão por chat — rebuild do transcript append-only (sobrevive a restart)."""
        cid = str(chat_id)
        if cid not in self.sessions:
            s = Session()
            e = self.store.entry(cid)
            s.history = self.store.history(cid, limit=16)
            s.yolo = bool(e.get("yolo", False))
            s.persona_overlay = e.get("persona_overlay", "")
            s.resume_attempts = int(e.get("resume_attempts", 0))
            s.reasoning_effort = e.get("reasoning_effort", "")
            s.title = e.get("title", "")
            s.voice_off = bool(e.get("voice_off", False))
            s.busy_mode = e.get("busy_mode", "queue")
            self.sessions[cid] = s
        return self.sessions[cid]

    def _append_turn(self, chat_id, s: Session, role: str, text: str) -> None:
        """Grava um turno: append-only no transcript + memória (trim p/ contexto)."""
        self.store.append(chat_id, role, text)         # disco: 1 linha (nunca reescreve a conversa)
        s.history.append((role, text))
        s.history[:] = s.history[-16:]

    def _save_meta(self, chat_id, s: Session) -> None:
        """Atualiza só os METADADOS (yolo/overlay/resume_attempts) — não toca no transcript."""
        self.store.update_entry(chat_id, yolo=s.yolo, persona_overlay=s.persona_overlay,
                                resume_attempts=s.resume_attempts, reasoning_effort=s.reasoning_effort,
                                title=s.title, voice_off=s.voice_off, busy_mode=s.busy_mode)

    def _all_session_ids(self) -> list[str]:
        return self.store.ids()

    def _home_file(self) -> Path:
        return Path(self.ws) / ".okami" / "home_chat.txt"

    def home_chat(self) -> str:
        """Chat 'casa' p/ entregar lembretes/agendamentos sem alvo explícito (/sethome). '' se não definido."""
        try:
            return self._home_file().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def set_home(self, chat_id) -> None:
        p = self._home_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(chat_id), encoding="utf-8")

    def prune_sessions(self, max_sessions: int = 500, max_age_days: float = 30.0) -> int:
        return self.store.prune(max_sessions=max_sessions, max_age_days=max_age_days)

    def resume_interrupted(self, auto_resume: bool = False, max_attempts: int = 1) -> None:
        """No boot: detecta sessões cuja última fala foi do USER (tarefa interrompida por restart/crash).
        Default = AVISA + oferece /retry. Com auto_resume, re-executa UMA vez (guarda anti-loop #7536)."""
        for cid in self._all_session_ids():
            s = self.session(cid)
            if not s.interrupted():
                continue
            last = s.history[-1][1]
            if auto_resume and s.resume_attempts < max_attempts:
                s.resume_attempts += 1
                self._save_meta(cid, s)                # marca a tentativa ANTES (sobrevive a novo crash)
                self.channel.send(cid, "↻ retomando a tarefa interrompida pelo restart…")
                s.busy = True
                self._spawn(lambda c=cid, t=last, ss=s: self._run(c, t, ss, resume=True))
            else:
                why = "tentei retomar e não rolou" if s.resume_attempts else "o gateway reiniciou"
                self.channel.send(cid, f"⚠ {why}: sua última mensagem ficou sem resposta — "
                                       f"«{last[:80]}». Mande /retry pra eu continuar.")


    def _evolve(self, chat_id, note: str) -> None:
        """Feedback EXPLÍCITO de estilo → evolui VOICE/PERSONA na hora (auto, sem go/no-go). §8."""
        from okami.learning import persona
        try:
            edit = persona.propose(note)
            persona.apply_evolution(self.ws, edit, approve=None)      # auto: não pergunta
            self.channel.send(chat_id, f"🧬 anotado ({edit.target}): {edit.text}\n(/undo p/ reverter)")
        except Exception as e:  # noqa: BLE001
            self.channel.send(chat_id, f"❌ {e}")

    def _observe(self, chat_id, user_text: str) -> None:
        """Observa o ESTILO do usuário e evolui sozinho (gradual). Silencioso; só avisa ao 'pegar'."""
        from okami.learning import persona
        pc = (self.cfg.persona if self.cfg is not None else None) or {}
        if not pc.get("observe", True):                # desligável via persona.observe: false
            return
        try:
            for _ in persona.observe(self.ws, user_text, scale=int(pc.get("gradual_scale", 1)),
                                     emit=lambda m: self.channel.send(chat_id, f"🧬 saquei: {m}")):
                pass
        except Exception:  # noqa: BLE001 — nunca quebra o chat (mas registra: #4 self-review)
            from okami import log
            log.dbg("persona.observe falhou", exc_info=True)

    def _maybe_compact(self, chat_id) -> None:
        """Transcript longo → gera um nó SUMMARY (compaction §6.4). A cada 40 turnos depois de 60."""
        if self.cfg is None:
            return
        n = int(self.store.entry(chat_id).get("node_count", 0))
        if n < 60 or n % 40 != 0:
            return
        from okami.llm import providers as prov
        try:
            convo = "\n".join(f"{r}: {t}" for r, t in self.store.history(chat_id, limit=40))
            summary = prov.complete_messages(self.cfg, [
                {"role": "system", "content": "Resuma a conversa em 1 parágrafo, preservando decisões, "
                 "fatos e pendências (o que importa p/ continuar)."},
                {"role": "user", "content": convo}]).strip()
            if summary:
                self.store.compact(chat_id, "[resumo da conversa anterior] " + summary[:1500])
        except Exception:  # noqa: BLE001 — compaction é best-effort
            from okami import log
            log.dbg("compaction falhou", exc_info=True)

    def _observe_llm(self, chat_id, s: "Session") -> None:
        """A cada N turnos (persona.llm_every), uma leitura mais RICA por LLM (pega sarcasmo pelo tom,
        nuances que a heurística não vê). Off por padrão (custo); ligue com persona.llm_every: 6."""
        pc = (self.cfg.persona if self.cfg is not None else None) or {}
        every = int(pc.get("llm_every", 0))
        if every <= 0 or (len(s.history) // 2) % every != 0:
            return
        from okami.learning import persona
        try:
            persona.observe_llm(self.cfg, self.ws, s.history, scale=int(pc.get("gradual_scale", 1)),
                                emit=lambda m: self.channel.send(chat_id, f"🧬 percebi: {m}"))
        except Exception:  # noqa: BLE001
            from okami import log
            log.dbg("persona.observe_llm falhou", exc_info=True)

    def _approve(self, chat_id, s: Session) -> Callable[[dict], bool]:
        def approve(req: dict) -> bool:
            if s.yolo or self.approval_mode == "yolo":     # YOLO explícito → autoaprova
                return True
            if self.approval_mode == "smart" and req.get("risk") == "low":
                return True
            if self.approval_mode == "off":                # "off" = não pergunta → NEGA sensível (fail-closed)
                return False
            import secrets
            nonce = secrets.token_hex(8)                 # = approval_id; amarra o botão a ESTE pedido (P1.3 anti-stale)
            from okami.core.approval import args_hash as _ahash
            self.approvals.create(                       # #7: registro durável single-use (sobrevive a restart)
                approval_id=nonce, tool=req.get("tool", "?"),
                args_hash=req.get("args_hash") or _ahash(req.get("args") or {}),
                risk=req.get("risk", "high"), category=req.get("category", ""),
                surface=self.surface, chat_id=str(chat_id), ttl=self.approval_timeout)
            q: queue.Queue = queue.Queue()
            self._pending[str(chat_id)] = (q, nonce)
            brief = ""                                   # mostra QUAL ação (tool + arg-chave) — #1/#9 target binding
            for _k in ("path", "cmd", "url", "name"):
                _v = (req.get("args") or {}).get(_k)
                if isinstance(_v, str) and _v:
                    brief = f" · {_k}={_v[:80]}"
                    break
            ask = f"⚠ Aprovar [{req.get('tool', '?')}]{brief}\n{req['reason']} (risco={req.get('risk', '?')})"
            _sa = getattr(self.channel, "send_approval", None)   # botões inline se o canal suportar
            if _sa:
                try:
                    _sa(chat_id, ask, nonce=nonce)
                except TypeError:                        # canal sem suporte a nonce → compat
                    _sa(chat_id, ask)
            else:
                self.channel.send(chat_id, ask + " (/yes ou /no)")
            try:
                ans = q.get(timeout=self.approval_timeout)
            except queue.Empty:
                ans = "/no"
                self.approvals.expire_if_pending(nonce)  # sem resposta → marca expirado no registro
            finally:
                self._pending.pop(str(chat_id), None)
            ok = ans.strip().lower() in ("/yes", "yes", "sim", "y", "ok")
            self.channel.send(chat_id, "✅ aprovado" if ok else "❌ negado")
            return ok
        return approve

    def handle(self, chat_id, text: str) -> None:
        if not self.channel.allowed(chat_id):
            self.channel.send(chat_id, "🚫 chat não autorizado.")
            return
        self._last_chat = str(chat_id)                 # alvo do notify_on_complete (#1/#8) best-effort
        text = (text or "").strip()
        cid = str(chat_id)
        if cid in self._pending:                       # resposta a uma aprovação pendente
            pend = self._pending[cid]
            q, want = pend if isinstance(pend, tuple) else (pend, "")   # tolera fila pura (compat)
            verb, _, got = text.partition(":")         # "/yes" | "/yes:<nonce>" (botão)
            if got and want and got != want:           # nonce velho/errado = clique stale → IGNORA
                self.channel.send(chat_id, "⌛ esse botão expirou (outra ação aconteceu). Use /yes ou /no.")
                return
            store = getattr(self, "approvals", None)   # ausente em endpoint bare (alguns testes/compat)
            if want and store is not None:             # #7: consome o registro durável (single-use + expiração)
                decision = "approved" if verb.strip().lower() in ("/yes", "yes", "sim", "y", "ok") else "denied"
                res = store.consume(want, decision)
                if not res.ok and res.reason != "desconhecido":   # já usado / expirado → recusa (não re-executa)
                    self.channel.send(chat_id, f"⌛ aprovação inválida ({res.reason}). Use /yes ou /no de novo.")
                    return
            q.put(verb)
            return
        if text.partition(":")[0].lower() in ("/yes", "/no"):   # aprovação sem nada pendente (clique dup/stale)
            self.channel.send(chat_id, "nada pendente pra aprovar agora.")
            return
        s = self.session(chat_id)
        low = text.lower()
        # --- slash registry: canonicaliza alias + "did you mean" (1 vez, no topo) ---
        import re as _re
        if text.startswith("/") and _re.match(r"^/[a-z?]+$", low.split(maxsplit=1)[0]):
            from okami import commands as _cmds
            tok = low.split(maxsplit=1)[0]
            cdef = _cmds.resolve(tok)
            if cdef is None:
                sg = _cmds.suggest(tok)
                hint = (" Você quis dizer " + ", ".join("/" + x for x in sg) + "?") if sg else " — /commands lista tudo."
                self.channel.send(chat_id, f"❓ comando desconhecido: {tok}.{hint}")
                return
            text = "/" + cdef.name + text[len(tok):]       # reescreve pro canônico → as branches casam
            low = text.lower()
        if low in ("/start", "/help", ""):
            self.channel.send(chat_id, self._help())
            return
        if low in ("/new", "/reset"):
            s.history.clear()
            self.store.reset(chat_id)                  # arquiva o transcript e zera a contagem
            self.channel.send(chat_id, "🧹 conversa reiniciada.")
            return
        if low == "/status":
            bg = f" · ▶{len(self._bg)} background" if self._bg else ""
            q = f" · 🕓{len(s.queued)} fila" if s.queued else ""
            ttl = f" · 📝 {s.title}" if s.title else ""
            mute = " · 🔇" if s.voice_off else ""
            self.channel.send(chat_id, f"agente {self.agent_id}{ttl} · "
                              f"{'ocupado' if s.busy else 'livre'} · {len(s.history) // 2} trocas · "
                              f"yolo={'on' if s.yolo else 'off'}{mute}{bg}{q}")
            return
        if low == "/yolo":
            s.yolo = True
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "⚡ YOLO on (auto-aprova nesta sessão).")
            return
        if low == "/normal":
            s.yolo = False
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "🔒 aprovação normal.")
            return
        if low.startswith("/voice"):
            arg = text[len("/voice"):].strip().lower()
            if arg in ("off", "mute", "0", "no"):
                s.voice_off = True
            elif arg in ("on", "1", "yes"):
                s.voice_off = False
            else:
                s.voice_off = not s.voice_off          # sem arg → alterna
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "🔈 áudio DESLIGADO nesta sessão." if s.voice_off
                              else "🔊 áudio LIGADO (respondo em voz quando o TTS está ativo).")
            return
        if low.startswith("/busy"):
            arg = text[len("/busy"):].strip().lower()
            if arg in ("queue", "fila"):
                s.busy_mode = "queue"
            elif arg in ("interrupt", "corta", "stop"):
                s.busy_mode = "interrupt"
            elif arg in ("", "status"):
                q = f" · {len(s.queued)} na fila" if s.queued else ""
                self.channel.send(chat_id, f"⏳ modo ocupado: {s.busy_mode}{q}. Opções: queue · interrupt.")
                return
            else:
                self.channel.send(chat_id, "uso: /busy queue (fila) | interrupt (corta a atual) | status")
                return
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, f"⏳ ocupado → {s.busy_mode}.")
            return
        if low in ("/reload", "/reloadconfig"):        # #12: hot-reload de config (sem reiniciar)
            ok, msg = self.reload_config()
            self.channel.send(chat_id, f"🔄 config recarregada — {msg}" if ok else f"✗ config inválida: {msg}")
            return
        if low == "/stop":
            s.cancel = True
            self.channel.send(chat_id, "⏹ parando após o passo atual…")
            return
        if low in ("/retry", "/continuar"):            # retoma a última tarefa que ficou sem resposta
            if s.busy:
                self.channel.send(chat_id, "⏳ já estou processando.")
                return
            if not s.interrupted():
                self.channel.send(chat_id, "nada interrompido para retomar.")
                return
            last = s.history[-1][1]                     # o USER pendente continua; _run não re-adiciona
            s.busy, s.cancel = True, False
            self._spawn(lambda: self._run(chat_id, last, s, resume=True))
            return
        if low.startswith("/feedback"):                # molda a identidade (§8), com go/no-go
            note = text[len("/feedback"):].strip()
            if not note:
                self.channel.send(chat_id, "uso: /feedback <como devo me comportar/falar>")
                return
            self._evolve(chat_id, note)                   # explícito → aplica na hora (auto)
            return
        if low in ("/undo", "/rollback"):              # reverte a última evolução de identidade
            from okami.learning import persona
            removed = persona.rollback(self.ws, 1)
            self.channel.send(chat_id, (f"↩ revertido: {removed[0].get('text')}" if removed
                                        else "nada para reverter."))
            return
        cmd0 = low.split(maxsplit=1)[0]
        if cmd0 in ("/like", "/dislike", "/different"):   # taste de design (§9): aprende o gosto
            from okami.learning import taste
            verdict = {"/like": "approved", "/dislike": "rejected", "/different": "want_different"}[cmd0]
            desc = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if not desc:
                self.channel.send(chat_id, f"uso: {cmd0} <o que achou do design (ex.: 'bootstrap, neon')>")
                return
            prof = taste.record_feedback(self.ws, verdict, desc)
            self.channel.send(chat_id, f"🎨 anotei o gosto (atrai={len(prof.attractors)}, "
                                       f"repele={len(prof.repulsors)}).")
            return
        if low.startswith("/think"):                   # esforço de raciocínio desta sessão (gpt-5/codex)
            arg = text[len("/think"):].strip().lower()
            if arg in ("", "off", "auto", "default"):
                s.reasoning_effort = ""
                self.channel.send(chat_id, "🧠 think no default do modelo. Níveis: minimal·low·medium·high.")
            else:
                s.reasoning_effort = arg
                self.channel.send(chat_id, f"🧠 think = {arg} (vale nesta sessão).")
            self._save_meta(chat_id, s)
            return
        if low.startswith("/persona"):                 # overlay TEMPORÁRIO de sessão (estilo /personality)
            from okami.learning import persona
            arg = text[len("/persona"):].strip()
            if arg.lower() in ("", "off", "reset", "normal"):
                s.persona_overlay = ""
                self.channel.send(chat_id, "🎭 persona padrão. Presets: " + ", ".join(persona.PERSONA_PRESETS))
            else:
                s.persona_overlay = persona.overlay(arg)
                self.channel.send(chat_id, f"🎭 nesta sessão: {arg} (/persona off p/ voltar)")
            self._save_meta(chat_id, s)
            return
        if low == "/sethome":                           # destino dos lembretes/cron sem alvo explícito
            self.set_home(chat_id)
            self.channel.send(chat_id, "🏠 este chat virou a CASA dos lembretes/agendamentos sem destino.")
            return
        if low.startswith("/topic"):                    # tópicos do Telegram já viram sessões separadas (auto)
            cur = ":" in cid and cid.rsplit(":", 1)[1]
            here = f"\nVocê está no tópico {cur} (conversa separada)." if cur else ""
            self.channel.send(chat_id, "🧵 cada TÓPICO do Telegram neste chat é uma conversa separada "
                              "(histórico/sessão próprios) — automático. Crie um tópico no app pra abrir "
                              "outra linha de conversa em paralelo." + here)
            return
        if low == "/commands":                          # registry: lista completa por categoria
            self.channel.send(chat_id, self._commands_text())
            return
        if low == "/usage":
            self.channel.send(chat_id, self._usage_text(chat_id))
            return
        if low == "/tools":
            self.channel.send(chat_id, self._tools_text())
            return
        if low == "/config":
            self.channel.send(chat_id, self._config_text())
            return
        if low == "/whoami":
            self.channel.send(chat_id, f"🪪 chat id: {chat_id} · agente: {self.agent_id}")
            return
        if low == "/models":                            # ANTES de /model (startswith colide)
            self.channel.send(chat_id, self._models_text())
            return
        if low.startswith("/model"):
            self.channel.send(chat_id, self._model_cmd(s, text[len("/model"):].strip()))
            self._save_meta(chat_id, s)
            return
        if low == "/compact":
            self.channel.send(chat_id, self._compact_now(chat_id, s))
            return
        if low == "/sessions":
            self.channel.send(chat_id, self._sessions_text(chat_id))
            return
        if low.startswith("/resume"):
            self.channel.send(chat_id, self._resume_cmd(chat_id, s, text[len("/resume"):].strip()))
            return
        if low.startswith("/export"):
            self.channel.send(chat_id, self._export_cmd(chat_id, text[len("/export"):].strip()))
            return
        if low.startswith("/title"):                   # nome amigável da conversa (aparece no /status e /sessions)
            arg = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if not arg:
                self.channel.send(chat_id, f"📝 título: {s.title}" if s.title else "sem título. Uso: /title <nome>")
                return
            s.title = arg[:80]
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, f"📝 conversa renomeada: {s.title}")
            return
        cmd_bg = low.split(maxsplit=1)[0]
        if cmd_bg in ("/background", "/bg"):            # roda EM PARALELO (sessão isolada) e avisa no fim
            prompt = text.split(maxsplit=1)[1].strip() if " " in text else ""
            parts = prompt.split(maxsplit=1)
            sub = parts[0].lower() if parts else ""
            if sub == "status":                        # /background status → lista persistida (durável)
                self.channel.send(chat_id, self._background_status(queued=len(s.queued)))
                return
            if sub in ("cancel", "kill", "stop"):      # /background cancel <id> → para a tarefa
                self.channel.send(chat_id, self._background_cancel(parts[1].strip() if len(parts) > 1 else ""))
                return
            if sub in ("log", "logs", "tail"):         # /background log <id> [linhas] → progresso ao vivo
                self.channel.send(chat_id, self._background_log(parts[1].strip() if len(parts) > 1 else ""))
                return
            if sub in ("--process", "--proc", "-p"):   # promove a PROCESSO OS (servidor/build) → kill real
                self.channel.send(chat_id, self._background_as_process(
                    chat_id, parts[1].strip() if len(parts) > 1 else "", yolo=s.yolo))
                return
            if not prompt:
                self.channel.send(chat_id, "uso: /background <tarefa> · /background --process <cmd> "
                                  "(servidor/build) · /background status · /background log <id> · "
                                  "/background cancel <id>. Rodo em paralelo e aviso no fim.")
                return
            self._spawn_background(chat_id, prompt, yolo=s.yolo)
            return
        if low.split(maxsplit=1)[0] in ("/process", "/proc", "/procs"):   # supervisão de PROCESSOS OS — kill REAL
            rest = text.split(maxsplit=1)[1].strip() if " " in text else ""
            pp = rest.split(maxsplit=1)
            psub = pp[0].lower() if pp else ""
            parg = pp[1].strip() if len(pp) > 1 else ""
            if psub in ("", "status", "list", "ls", "ps"):
                self.channel.send(chat_id, self._process_status())
            elif psub in ("log", "logs", "tail"):
                self.channel.send(chat_id, self._process_log(parg))
            elif psub in ("kill", "stop", "term"):
                self.channel.send(chat_id, self._process_kill(parg))
            elif psub in ("signal", "sig"):
                self.channel.send(chat_id, self._process_signal(parg))
            else:
                self.channel.send(chat_id, "uso: /process status · /process log <id> [linhas] · "
                                  "/process kill <id> · /process signal <id> <SINAL>. (kill imediato, real)")
            return
        from okami.automation.scheduler import Scheduler, infer_commitment   # §11: "me lembra de X amanhã" → agenda
        ic = infer_commitment(text, time.time())
        if ic:
            schedule, prompt = ic
            job = Scheduler(".").add(schedule, prompt, agent=self.agent_id, target=str(chat_id))
            self.channel.send(chat_id, f"⏰ agendei [{job['schedule']}]: {prompt}")
            return
        if s.busy:                                      # ocupado: enfileira (e corta a atual se modo interrupt)
            s.queued.append((text, self._img.pop(cid, None)))
            if s.busy_mode == "interrupt":
                s.cancel = True
                self.channel.send(chat_id, "⏹ interrompendo a atual — já começo a sua nova mensagem.")
            else:
                self.channel.send(chat_id, f"⏳ guardei na fila (#{len(s.queued)}) — começo quando a atual terminar.")
            return
        s.busy = True
        s.cancel = False
        self._spawn(lambda: self._run(chat_id, text, s, images=self._img.pop(cid, None)))

    def _react(self, chat_id, emoji: str) -> None:
        """Reage à última mensagem do usuário (Telegram). Best-effort, opt-in (self.reactions)."""
        if not self.reactions:
            return
        fn = getattr(self.channel, "set_reaction", None)
        mid = self._last_msg_id.get(str(chat_id))
        if fn and mid:
            try:
                fn(chat_id, mid, emoji)
            except Exception:  # noqa: BLE001
                pass

    def _turn_footer(self, s: "Session", stats: dict, elapsed: float) -> str:
        """Rodapé de custo por resposta: `· ctx N% · X tok (in↑ out↓) · Ys`. Sóbrio, 1 linha, dim."""
        from okami.llm.usage import CanonicalUsage, format_tokens
        parts: list[str] = []
        try:                                              # ctx %: quão cheia está a janela do modelo
            pc = self.cfg.provider() if self.cfg else None
            if pc:
                from okami.llm.providers import context_window_tokens
                budget = max(1, int(context_window_tokens(pc) * (pc.chars_per_token or 4.0)))
                used = sum(len(t) for _, t in s.history)
                parts.append(f"ctx {min(100, round(100 * used / budget))}%")
        except Exception:  # noqa: BLE001 — footer é cosmético, nunca quebra o turno
            pass
        u = CanonicalUsage.from_dict((stats or {}).get("usage") or {})
        if u.total_tokens:
            tok = f"{format_tokens(u.total_tokens)} tok ({format_tokens(u.input_tokens)}↑ {format_tokens(u.output_tokens)}↓)"
            if u.cache_read_tokens:
                tok += f" · {format_tokens(u.cache_read_tokens)} cache"
            parts.append(tok)
        parts.append(f"{elapsed:.1f}s")
        return "· " + "  ·  ".join(parts) if parts else ""

    def _pm(self):
        from okami.core.processes import ProcessManager
        return ProcessManager(self.ws)

    def process_brief(self) -> list[dict]:
        """Lista de processos OS p/ o painel /agents (best-effort, nunca lança)."""
        try:
            return self._pm().list()
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _fmt_processes(procs: list[dict]) -> str:
        """Bloco de processos OS (servidor/build longo) — kill IMEDIATO, ao contrário do background cooperativo."""
        icon = {"running": "▶", "exited": "✅", "unknown": "·"}
        out = ["⚙ processos (OS real — kill imediato: /process kill <id>):"]
        for p in procs[-15:]:
            st = p.get("status", "?")
            ec = p.get("exit_code")
            tail = f" → exit {ec}" if st == "exited" and ec is not None else ""
            flag = " 🔌" if p.get("interactive") else ""
            out.append(f"  {icon.get(st, '·')} {p['id']} [{st}{tail}]{flag} {(p.get('cmd') or '')[:48]}")
        return "\n".join(out)

    def _background_status(self, *, queued: int = 0) -> str:
        """Visão UNIFICADA: fila da sessão + tarefas /background (cancel cooperativo) + processos OS (kill real)."""
        import datetime as _dt
        jobs = self._bgreg.list(15)
        out: list[str] = []
        if queued:                                       # mensagens enfileiradas (digitou enquanto ocupado)
            out.append(f"⏳ fila desta sessão: {queued} aguardando")
        if jobs:
            icon = {"running": "▶", "done": "✅", "failed": "❌", "interrupted": "⏸", "cancelled": "⏹"}
            out.append("📋 tarefas /background (durável — sobrevive a restart):")
            for j in jobs:
                when = (_dt.datetime.fromtimestamp(j["started_at"]).strftime("%d/%m %H:%M")
                        if j.get("started_at") else "?")
                out.append(f"  {icon.get(j.get('state'), '·')} #{j['id']} [{when}] {(j.get('prompt') or '')[:60]}")
        else:
            out.append("▶ nenhuma tarefa /background ainda.")
        try:
            procs = self._pm().list()
        except Exception:  # noqa: BLE001
            procs = []
        if procs:                                        # mostra TAMBÉM os processos relevantes (pedido do review)
            out.append("")
            out.append(self._fmt_processes(procs))
        return "\n".join(out)

    def _background_as_process(self, chat_id, cmd: str, *, yolo: bool) -> str:
        """/background --process <cmd>: sobe um servidor/build como PROCESSO OS (kill real), não thread.
        Comando sensível/destrutivo direto do chat só com /yolo — senão fail-closed (DNA de segurança)."""
        if not cmd:
            return ("uso: /background --process <comando> (ex.: npm run dev) — sobe como PROCESSO OS, "
                    "com kill REAL (/process kill <id>) e log paginado (/process log <id>).")
        from okami.core.approval import classify
        sens = classify("process_start", {"cmd": cmd})
        if sens and not yolo:                            # destrutivo/sensível sem yolo → NEGA
            return (f"🚫 recusei: {sens.reason} (risco {sens.risk}). Comando sensível direto do chat só com "
                    "/yolo nesta sessão — ou peça pra MIM rodar (aí passa pelo go/no-go).")
        try:
            from okami.core.sandbox import SandboxPolicy
            pol = SandboxPolicy.from_config((self.cfg.sandbox if self.cfg else None) or {})
        except Exception:  # noqa: BLE001
            pol = None
        try:
            meta = self._pm().start(cmd, pol, notify=True)   # notify → aviso quando terminar
        except ValueError as e:                          # sandbox bloqueou (sensível/docker exigido)
            return f"✗ não subiu: {e}"
        except Exception as e:  # noqa: BLE001
            return f"✗ falha ao subir o processo: {e}"
        return (f"⚙ processo {meta['id']} no ar (PID {meta['pid']}) — kill real: /process kill {meta['id']} · "
                f"log: /process log {meta['id']}. Te aviso quando terminar.")

    def _process_status(self) -> str:
        try:
            procs = self._pm().list()
        except Exception:  # noqa: BLE001
            procs = []
        if not procs:
            return ("⚙ nenhum processo OS agora. Servidores/builds longos que o agente sobe (process_start) "
                    "aparecem aqui — com kill imediato (/process kill <id>), diferente do background cooperativo.")
        return self._fmt_processes(procs)

    def _process_log(self, arg: str) -> str:
        """/process log <id> [linhas] [offset]. Sem offset = ÚLTIMAS N linhas; com offset = a partir dela.
        Mostra a faixa (X–Y de Z) e um link explícito p/ a PRÓXIMA página."""
        toks = arg.split()
        if not toks:
            return "uso: /process log <id> [linhas] [offset]. Ex.: /process log ab12 40 0 (do começo)."
        pid = toks[0]
        n = int(toks[1]) if len(toks) > 1 and toks[1].lstrip("-").isdigit() else 30
        explicit = len(toks) > 2 and toks[2].lstrip("-").isdigit()
        offset = int(toks[2]) if explicit else -n        # default: as últimas N linhas
        page = self._pm().log_page(pid, offset=offset, limit=n)
        if not page["lines"]:
            return f"📄 processo {pid}: sem log nessa faixa (ou id inexistente)."
        start, end, total = page["offset"] + 1, page["offset"] + page["shown"], page["total"]
        out = [f"📄 processo {pid} — linhas {start}–{end} de {total}:"]
        out += ["  " + ln for ln in page["lines"]]
        if end < total:                                  # próxima página explícita
            out.append(f"… +{total - end} linha(s): /process log {pid} {n} {end}")
        return "\n".join(out)

    def _process_kill(self, arg: str) -> str:
        toks = arg.split()
        if not toks:
            return "uso: /process kill <id> (ids em /process status)."
        pid = toks[0]
        if self._pm().poll(pid).get("status") == "unknown":
            return f"✗ processo {pid} não existe (veja /process status)."
        ok = self._pm().kill(pid)
        return f"🛑 processo {pid} morto (SIGTERM no grupo)." if ok else f"✗ não consegui matar {pid}."

    def _process_signal(self, arg: str) -> str:
        toks = arg.split()
        if len(toks) < 2:
            return "uso: /process signal <id> <SINAL> (ex.: HUP, KILL, USR1, STOP, CONT)."
        pid, name = toks[0], toks[1].upper().lstrip("SIG")
        ok = self._pm().signal(pid, name)
        return f"📶 sinal {name} → {pid}." if ok else f"✗ não consegui sinalizar {pid} (id/sinal inválido?)."

    def _background_log(self, arg: str) -> str:
        toks = arg.split()
        if not toks or not toks[0].lstrip("#").isdigit():
            return "uso: /background log <id> [linhas] (ids em /background status)."
        bid = int(toks[0].lstrip("#"))
        n = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else 30
        lines = self._bgreg.tail(bid, n)
        if not lines:
            return f"📄 background #{bid}: sem log ainda (ou id inexistente)."
        return f"📄 background #{bid} (últimas {len(lines)} linhas):\n" + "\n".join("  " + ln for ln in lines)

    def _background_cancel(self, arg: str) -> str:
        a = arg.lstrip("#").strip()
        if not a.isdigit():
            return "uso: /background cancel <id> (veja os ids em /background status)."
        bid = int(a)
        ev = self._bg_cancel.get(bid)
        if ev is None:
            return (f"✗ background #{bid} não está rodando agora (já terminou, foi cancelado, ou era de "
                    "outra sessão/processo). Veja /background status.")
        ev.set()
        return (f"⏹ cancelando background #{bid} — para no próximo passo (cooperativo). Se ele subiu um "
                "servidor/build, veja /process status e mate na hora com /process kill <id>.")

    def _spawn_background(self, chat_id, prompt: str, *, yolo: bool = False) -> None:
        """/background: roda `prompt` numa tarefa ISOLADA (não toca no histórico da sessão), em paralelo,
        e devolve o resultado quando terminar. Aprovação fail-closed (só ações seguras) a menos que a
        sessão esteja em yolo — em background não dá pra pedir /yes interativo."""
        bid = self._bgreg.add(prompt)                    # PERSISTE (durável): id/prompt/estado/tempos
        ev = threading.Event()                           # sinal de cancelamento cooperativo (como o /stop)
        self._bg_cancel[bid] = ev
        self._bg[bid] = prompt[:60]
        self.channel.send(chat_id, f"▶ background #{bid} rodando — sigo livre pra conversar; te aviso no fim. "
                          f"(/background cancel {bid} pra parar)")

        from okami.gateway.background import event_line_plain

        def _on_ev(e, _bid=bid):                         # stream AO VIVO: cada passo do harness → log do job
            self._bgreg.append_log(_bid, event_line_plain(e))

        def _bgrun(_bid=bid, _p=prompt, _yolo=yolo, _ev=ev):
            try:
                approve = (lambda req: True) if _yolo else (lambda req: False)   # fail-closed sem interação
                task = self.run_task(self.cfg, self.ws, _p, approve=approve, surface=self.surface,
                                     cancel=_ev.is_set,   # harness checa entre passos → para no /background cancel
                                     on_event=_on_ev)     # progresso ao vivo → /background log <id>
                if _ev.is_set():
                    self._bgreg.append_log(_bid, "⏹ cancelado")
                    self._bgreg.finish(_bid, state="cancelled", result="cancelado pelo usuário")
                    self.channel.send(chat_id, f"⏹ background #{_bid} cancelado.")
                else:
                    out = (getattr(task, "result", "") or "").strip() or "(sem saída textual)"
                    self._bgreg.append_log(_bid, "✅ concluído")
                    self._bgreg.finish(_bid, state="done", result=out)
                    self.channel.send(chat_id, f"✅ background #{_bid} pronto:\n{out}")
            except Exception as e:  # noqa: BLE001 — background nunca derruba o endpoint
                self._bgreg.append_log(_bid, f"❌ erro: {e}")
                self._bgreg.finish(_bid, state="failed", result=str(e))
                self.channel.send(chat_id, f"❌ background #{_bid} falhou: {e}")
            finally:
                self._bg.pop(_bid, None)
                self._bg_cancel.pop(_bid, None)

        self._spawn(_bgrun)

    def _run(self, chat_id, text: str, s: Session, resume: bool = False, images=None) -> None:
        if resume:                                        # retomada: o USER já está no transcript
            ctx = _history_block(s.history[:-1], max_chars=self.max_history_chars)
        else:
            ctx = _history_block(s.history, max_chars=self.max_history_chars)   # histórico PRIOR
            self._append_turn(chat_id, s, "USER", text)   # grava a fala EM ANDAMENTO (detecta interrupção)
        if s.persona_overlay:                              # overlay de sessão prevalece sobre o tom padrão
            ctx = s.persona_overlay + ("\n\n" + ctx if ctx else "")
        genesis = genesis_pending(self.ws)                 # 1ª config (§8.2): onboarding de primeiro contato
        if genesis:
            ctx = GENESIS_BLOCK + ("\n\n" + ctx if ctx else "")
        if images:                                         # foto recebida → salva no inbox + instrui (§13)
            import json as _json
            import shutil
            inbox = Path(self.ws) / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            rels, abss = [], []
            for img in images:
                dst = inbox / Path(img).name
                try:
                    shutil.copy(img, dst)
                except Exception:  # noqa: BLE001
                    dst = Path(img)
                rels.append(f"inbox/{dst.name}")
                abss.append(str(dst))
            note = ("IMAGEM(NS) que o usuário enviou: " + ", ".join(f"`{r}`" for r in rels)
                    + ". Para GERAR/TRANSFORMAR a partir dela(s) (ex.: infográfico, variação), chame "
                    f"generate_image com references={_json.dumps(rels)} — NÃO edite o arquivo você mesmo, "
                    "o gpt-image-2 é quem gera.")
            ctx = note + ("\n\n" + ctx if ctx else "")
            images = abss                                  # vision lê os caminhos no inbox
        _typing = getattr(self.channel, "send_typing", None)   # indicador "digitando…" (Telegram)
        if _typing:
            try:
                _typing(chat_id)
            except Exception:  # noqa: BLE001 — typing nunca quebra o turno
                pass
        self.channel.send(chat_id, f"🧠 {self.agent_id} está pensando…")
        self._react(chat_id, "👀")                       # 👀 = processando (Telegram)
        try:
            approve = self._approve(chat_id, s)
            on_ev = self.on_event
            if genesis:                                   # na gênese, escrever a própria identidade é o
                base = approve                            # OBJETIVO → auto-aprova identity_file (sem /yes a cada arquivo)
                approve = lambda req: True if req.get("category") == "identity_file" else base(req)  # noqa: E731
                # identidade já é auto-aprovada aqui → não assustar o usuário com "⚠ aprovação" no terminal.
                if on_ev is not None:
                    def on_ev(e, _b=self.on_event):       # noqa: E306
                        if e.get("kind") == "approval_request" and e.get("category") == "identity_file":
                            return
                        _b(e)
                # stubs de SOUL/VOICE/PERSONA são placeholders NOSSOS → já "conhecidos" (sem ✗ grounding).
                kw_pre = ["SOUL.md", "VOICE.md", "PERSONA.md", "USER.md"]
            else:
                kw_pre = None
            kw = {"approve": approve, "extra_context": ctx, "cancel": lambda: s.cancel}
            if kw_pre:
                kw["prelearned_files"] = kw_pre
            if on_ev is not None:                         # progresso ao vivo (tool-calls, loop, compaction…)
                kw["on_event"] = on_ev
            if s.reasoning_effort:                        # /think desta sessão → vence o default do provider
                kw["reasoning_effort"] = s.reasoning_effort
            if s.model_override:                          # /model desta sessão → vence o default
                kw["model"] = s.model_override
            if images:                                    # vision (§6) só quando veio foto (compat c/ runners simples)
                kw["images"] = images
            kw.setdefault("surface", self.surface)        # tool policy por superfície (P1.4)
            _t0 = time.time()                              # cronômetro da resposta (footer ctx·tok·tempo)
            task = self.run_task(self.cfg, self.ws, text, **kw)
            _elapsed = time.time() - _t0
            stats = getattr(task, "stats", None) or {}     # tokens do turno (custo §A5)
            if stats.get("usage"):
                try:
                    self.store.add_usage(chat_id, stats["usage"], served_by=stats.get("served_by", ""))
                except Exception:  # noqa: BLE001 — contabilidade nunca quebra o turno
                    pass
            reply = task.result or task.reason or f"({task.state.value})"
            self._append_turn(chat_id, s, "AGENTE", reply)  # fecha o par → não é mais "interrompida"
            s.resume_attempts = 0                          # concluiu → zera a guarda de resume
            self._save_meta(chat_id, s)
            # Papo casual (respond puro, sem critério nem ação com efeito) NÃO leva prefixo robótico —
            # é conversa, não "tarefa concluída". Só decora quando houve trabalho de verdade.
            chatty = (task.state.name == "COMPLETE" and not task.exit_criteria
                      and not any(s.effect for s in task.steps))
            prefix = "" if chatty else {"COMPLETE": "✅ ", "BLOCKED": "⚠ ",
                                        "NEEDS_INPUT": "❓ "}.get(task.state.name, "❌ ")
            self.channel.send(chat_id, prefix + reply)
            footer = self._turn_footer(s, stats, _elapsed)   # linha de custo: ctx · tokens · tempo
            if footer:
                self.channel.send(chat_id, footer)
            self._react(chat_id, {"COMPLETE": "👍", "BLOCKED": "👎",
                                  "NEEDS_INPUT": "🤔"}.get(task.state.name, "👎"))
            if not s.voice_off:                          # /voice off muta o áudio nesta sessão
                self._maybe_voice(chat_id, reply)
            self._observe(chat_id, text)                  # aprende o estilo do usuário (gradual, auto)
            self._observe_llm(chat_id, s)                 # a cada N turnos, leitura mais rica por LLM
            self._maybe_compact(chat_id)                  # transcript longo → nó SUMMARY (§6.4)
        except Exception as e:  # noqa: BLE001 — USER já está no transcript → detectável como interrompido
            self.channel.send(chat_id, f"❌ erro: {e}")
            self._react(chat_id, "👎")
        finally:
            s.busy = False
            s.cancel = False
            if s.queued:                                 # drena a fila: roda a próxima mensagem guardada
                nxt_text, nxt_img = s.queued.pop(0)
                s.busy = True
                self._spawn(lambda t=nxt_text, im=nxt_img: self._run(chat_id, t, s, images=im))

    def _maybe_voice(self, chat_id, text: str) -> None:
        if not self.tts:
            return
        try:
            import os
            import secrets
            import tempfile
            out = os.path.join(tempfile.gettempdir(), f"okami_tts_{secrets.token_hex(4)}.mp3")
            self.tts.synthesize(text[:1200], out)
            self.channel.send_audio(chat_id, out)
        except Exception:  # noqa: BLE001 — TTS é best-effort, nunca quebra a resposta
            pass

    def poll_once(self) -> None:
        for msg in self.channel.poll():
            mid = getattr(msg, "msg_id", "")
            if mid:                                        # idempotência por turno (#3): entrega duplicada → ignora
                if mid in self._seen_msgs:
                    continue
                self._seen_msgs[mid] = True
                if len(self._seen_msgs) > 1000:            # LRU simples (descarta o mais antigo)
                    self._seen_msgs.popitem(last=False)
                self._last_msg_id[str(msg.chat_id)] = mid  # alvo das reações 👀/👍/👎
            text = msg.text
            if msg.audio and self.stt:                 # nota de voz → transcreve (Whisper)
                try:
                    text = self.stt.transcribe(msg.audio)
                    self.channel.send(msg.chat_id, f"🎤 ouvi: «{text}»")
                except Exception as e:  # noqa: BLE001
                    self.channel.send(msg.chat_id, f"❌ não entendi o áudio: {e}")
                    continue
            if getattr(msg, "image", None):            # foto → vision (§6)
                self._img[str(msg.chat_id)] = msg.image
                self.handle(msg.chat_id, text or "Analise a imagem que enviei.")
                continue
            if text:
                self.handle(msg.chat_id, text)
        self._notify_completed_processes()

    def apply_config(self, cfg) -> list[str]:
        """Re-aplica em quente SÓ os campos seguros da nova config (#12). Devolve o que mudou."""
        changed = []
        new_mode = (getattr(cfg, "approvals", None) or {}).get("mode", self.approval_mode)
        if new_mode != self.approval_mode:
            self.approval_mode = new_mode
            changed.append(f"aprovação={new_mode}")
        old_sb = (getattr(self.cfg, "sandbox", None) or {})
        new_sb = (getattr(cfg, "sandbox", None) or {})
        if new_sb != old_sb:
            changed.append("sandbox")
        self.cfg = cfg                                  # persona/sandbox/modelo entram na próxima tarefa
        return changed

    def reload_config(self) -> tuple[bool, str]:
        """Recarrega okami.yaml/local do disco e aplica os campos seguros. (False, erro) se inválida."""
        from okami.config import load_config
        try:
            cfg = load_config()                        # valida ANTES de aplicar (config quebrada não derruba)
        except Exception as e:  # noqa: BLE001
            return False, str(e)
        changed = self.apply_config(cfg)
        return True, (", ".join(changed) if changed else "sem mudanças aplicáveis em quente")

    def _notify_completed_processes(self) -> None:
        """Fila de notificações de processo (#1/#8/#P1.4): conclusão + watch hits, avisa no chat."""
        chat = getattr(self, "_last_chat", None)
        if not chat:
            return
        try:
            from okami.core.processes import ProcessManager
            notes = ProcessManager(self.ws).drain_notifications()
        except Exception:  # noqa: BLE001
            return
        for n in notes:
            if n.get("kind") == "watch":
                self.channel.send(chat, f"👁 processo {n['id']}: padrão «{n['pattern']}» apareceu "
                                  f"({n['count']}×): {str(n.get('cmd', ''))[:50]}")
            else:
                self.channel.send(chat, f"✅ processo {n['id']} terminou (exit={n.get('exit_code')}): "
                                  f"{str(n.get('cmd', ''))[:60]}")

    def loop(self) -> None:
        try:                                            # boot: registra o menu '/' (Telegram setMyCommands)
            getattr(self.channel, "start", lambda: None)()
        except Exception:  # noqa: BLE001
            pass
        try:                                            # SIGHUP → hot-reload (convenção de daemon)
            import signal as _sig
            _sig.signal(_sig.SIGHUP, lambda *_: setattr(self, "_reload_req", True))
        except (ValueError, AttributeError, OSError):
            pass                                        # não-main-thread / sem SIGHUP (Windows)
        try:                                            # #P1.4: recovery de órfão no boot (processo morto sem exit)
            from okami.core.processes import ProcessManager
            ProcessManager(self.ws).reconcile()
        except Exception:  # noqa: BLE001
            pass
        try:                                            # /background durável: job 'running' que o restart matou → interrupted
            self._bgreg.reconcile()
            self._bgreg.prune()
        except Exception:  # noqa: BLE001
            pass
        while self.running:
            try:
                if getattr(self, "_reload_req", False):
                    self._reload_req = False
                    ok, msg = self.reload_config()
                    from okami import log
                    (log.dbg if ok else log.warn)(f"SIGHUP reload: {'ok ' if ok else 'falhou '}{msg}")
                self.poll_once()
                pace = getattr(self.channel, "poll_interval", 0)   # Telegram long-polla (0); REST espera
                if pace:
                    time.sleep(pace)
            except Exception:  # noqa: BLE001 — rede instável não derruba o bot
                time.sleep(3)
