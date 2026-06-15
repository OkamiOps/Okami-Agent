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

from okami.core.approval import smart_judge        # juiz LLM de aprovação no modo smart (item 13)
from okami.core.redact import redact               # DLP de saída (#7 item 2): mascara segredo antes do send
from okami.gateway.endpoint_commands import EndpointCommandsMixin
from okami.gateway.genesis import GENESIS_BLOCK, _history_block, genesis_pending
from okami.gateway.sessions import TranscriptStore
from okami.i18n import t as _tr

# Superfícies REMOTAS (o dono não está no terminal) → chat não-autorizado entra no fluxo de pareamento
# (recebe código, dono aprova pelo CLI). CLI/terminal a pessoa já é o dono → recusa seca.
_REMOTE_SURFACES = {"telegram", "group", "slack", "discord", "mattermost", "api"}

# Convenção de anexos (estilo Hermes): entra no system_extra quando o canal entrega mídia nativa.
MEDIA_HINT = (
    "ENVIO DE ARQUIVOS NESTE CANAL: para entregar um arquivo ao usuário (imagem, PDF, planilha, "
    "áudio, vídeo, zip…), inclua `MEDIA:<caminho_absoluto>` numa linha própria da resposta final "
    "(ex.: MEDIA:/tmp/relatorio.pdf). O gateway converte em anexo nativo — NÃO cole o conteúdo do "
    "arquivo no texto. Diretivas opcionais (numa linha antes das tags): [[as_document]] manda imagem "
    "como documento (sem compressão); [[audio_as_voice]] manda .ogg/.opus como mensagem de voz. "
    "Use apenas caminhos de arquivos que EXISTEM no disco."
)


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
        self.provider_override = ""      # provider desta sessão (/model <provider>) — ex.: codex (OpenAI via assinatura)
        self.title = ""                  # nome amigável da conversa (/title) — aparece no /status e /sessions
        self.voice_off = False           # /voice off → não responde em áudio (TTS) nesta sessão
        self.busy_mode = "queue"         # ocupado + nova msg: queue (fila) | interrupt (corta a atual)
        self.queued: list = []           # mensagens em fila (runtime; não persiste)
        self.remote_spec: str | None = None  # alias/host do ambiente remoto ATIVO (SSH/Tailscale) — multi-turno
        self.approved_cats: set[str] = set()  # categorias aprovadas PRA SESSÃO (Hermes): não pergunta de
        #                                       novo (ex.: aprovou 'destructive_shell' uma vez → libera o resto)

    def interrupted(self) -> bool:
        """Tarefa interrompida = histórico termina numa fala do USER sem resposta do AGENTE."""
        return bool(self.history) and self.history[-1][0] == "USER"


class AgentEndpoint(EndpointCommandsMixin):
    """Liga um agente ao seu canal; gerencia sessões por chat."""

    def __init__(self, agent_id: str, cfg, ws, channel, run_task: Callable,
                 approval_mode: str = "manual", approval_timeout: float = 120.0,
                 max_history_chars: int = 6000, stt=None, tts=None, spawn: Callable | None = None,
                 auto_resume: bool = False, max_sessions: int = 500, on_event: Callable | None = None,
                 reactions: bool = False, agent_home=None, open_fs: bool = False, allow_paths=None):
        self.on_event = on_event             # progresso ao vivo (tool-calls/loop/compact) — chat liga, Telegram não
        self.agent_id = agent_id
        self.cfg = cfg
        self.ws = ws                         # workspace OPERACIONAL (arquivos): CLI=CWD, gateway=casa do agente
        self.home = agent_home or ws         # CASA do agente (sessões/memória/identidade) — ISOLADA do projeto
        self.open_fs = open_fs               # DONO no CLI alcança todo o FS; Telegram/grupo = False (confinado)
        self.allow_paths = list(allow_paths or [])   # pastas extras liberadas além do workspace (config tools.allow_paths)
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
        self.store = TranscriptStore(self.home)  # 2 camadas: metadados + transcript (na CASA, não no projeto)
        from okami.gateway.approvals import ApprovalStore
        self.approvals = ApprovalStore(ws)   # aprovação como objeto persistente single-use (#7)
        from okami.gateway.pairing import PairingStore
        self._pairing = PairingStore(self.home)   # allowlist dinâmico: chat pede acesso → dono aprova (CLI)
        from okami.gateway.goals import GoalStore
        self._goals = GoalStore(self.home or self.ws)   # /goal: objetivo persistente por chat (item 41)
        from okami.gateway.circuit import PlatformBreaker
        self._breaker = PlatformBreaker()               # item 23: circuit breaker por plataforma
        self.sessions: dict[str, Session] = {}
        self._sess_lock = threading.Lock()   # serializa a transição busy/fila (check-then-set + drain) → 1
        #                                      tarefa por sessão mesmo com canal e _run em threads diferentes
        self._pending: dict[str, queue.Queue] = {}
        self._clarify_pending: dict[str, tuple] = {}   # #8 item 1: pergunta do agente esperando resposta do dono
        self.clarify_timeout = max(approval_timeout, 300.0)   # clarify pode esperar mais que uma aprovação
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
            s.approved_cats = set(e.get("approved_cats", []) or [])   # aprovações de sessão (sobrevivem a restart)
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
                                title=s.title, voice_off=s.voice_off, busy_mode=s.busy_mode,
                                approved_cats=sorted(s.approved_cats))

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

    def _notify_owner(self, chat_id, msg: str) -> bool:
        """Entrega FORA-DO-TURNO ao dono (#7 item 3) — usada por tarefas de longa duração (vigia/loop/
        lembrete, itens 10/14/19) p/ "tocar" o dono sem esperar o fim do turno. Vai pro home_chat (alvo
        canônico de lembretes) ou, na falta dele, pro chat de origem. Redige segredo SEMPRE (#7 item 2).
        Com a flag notifications.desktop ligada, também dispara notificação desktop (#7 item 4), best-effort.
        Devolve True se conseguiu entregar pelo canal; False se o send falhou."""
        safe = redact(msg or "")
        target = self.home_chat() or chat_id
        ok = False
        try:
            self.channel.send(target, "[notify] " + safe)
            ok = True
        except Exception:  # noqa: BLE001 — canal caiu? não deixa a notificação derrubar a tarefa
            ok = False
        # item 4 — sink desktop (best-effort, atrás da flag): "toca" o dono na máquina dele também.
        if self._desktop_enabled():
            try:
                from okami.core.desktop import desktop_notify
                desktop_notify("Okami", safe)
            except Exception:  # noqa: BLE001 — desktop é aviso, não operação crítica
                pass
        return ok

    def _desktop_enabled(self) -> bool:
        """True se notifications.desktop está ligado na config (fail-open p/ cfg dict/objeto/None)."""
        cfg = self.cfg
        notif = getattr(cfg, "notifications", None)
        if notif is None and isinstance(cfg, dict):       # cfg pode chegar como dict cru (compat)
            notif = cfg.get("notifications")
        if isinstance(notif, dict):
            return bool(notif.get("desktop"))
        return bool(getattr(notif, "desktop", False))

    def _emit_pairing_prompt(self, chat_id) -> None:
        """Chat não-autorizado: gera/reusa um código de pareamento e instrui o usuário a pedir ao dono
        que aprove pelo CLI (`okami pair approve <code>`). Deny-by-default segue — só o dono libera."""
        code = self._pairing.request_code(chat_id)
        if not code:                                     # corrida: aprovado entre o gate e aqui → segue
            self.handle(chat_id, "/help")
            return
        self.channel.send(chat_id, "🔐 " + _tr(
            "gw.pairing_prompt",
            _default=("access not authorized yet. Your pairing code is *{code}* — ask the owner to "
                      "approve it with `okami pair approve {code}` (or `okami pair add {chat}`)."),
            code=code, chat=chat_id))

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
                self.channel.send(cid, _tr("gw.resuming", _default="↻ resuming the task interrupted by the restart…"))
                s.busy = True
                self._spawn(lambda c=cid, t=last, ss=s: self._run(c, t, ss, resume=True))
            else:
                why = (_tr("gw.resume_retry_failed", _default="I tried to resume and it didn't work")
                       if s.resume_attempts
                       else _tr("gw.gateway_restarted", _default="the gateway restarted"))
                self.channel.send(cid, "⚠ " + _tr(
                    "gw.interrupted_notice",
                    _default="{why}: your last message went unanswered — «{last}». Send /retry to continue.",
                    why=why, last=last[:80]))


    def _evolve(self, chat_id, note: str) -> None:
        """Feedback EXPLÍCITO de estilo → evolui VOICE/PERSONA na hora (auto, sem go/no-go). §8."""
        from okami.learning import persona
        try:
            edit = persona.propose(note)
            persona.apply_evolution(self.ws, edit, approve=None)      # auto: não pergunta
            self.channel.send(chat_id, "🧬 " + _tr(
                "gw.evolve_noted", _default="noted ({target}): {text}\n(/undo to revert)",
                target=edit.target, text=edit.text))
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
                                     emit=lambda m: self.channel.send(chat_id, "🧬 " + _tr(
                                         "gw.observe_got_it", _default="got it: {m}", m=m))):
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
        from okami.llm.aux import aux_complete   # compressão é FUNDO → modelo auxiliar barato (item 57)
        try:
            convo = "\n".join(f"{r}: {t}" for r, t in self.store.history(chat_id, limit=40))
            summary = aux_complete(self.cfg, "compress", [
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
                                emit=lambda m: self.channel.send(chat_id, "🧬 " + _tr(
                                    "gw.observe_noticed", _default="noticed: {m}", m=m)))
        except Exception:  # noqa: BLE001
            from okami import log
            log.dbg("persona.observe_llm falhou", exc_info=True)

    def _ask_clarify(self, chat_id, question, options) -> str | None:
        """Pergunta BLOQUEANTE ao dono (#8 item 1): entrega a pergunta (+ menu numerado se houver
        opções) e espera a resposta, que chega por handle() de OUTRA thread. Mesma mecânica da
        aprovação — roda na thread do TURNO, destrava quando o dono responde, ou None no timeout."""
        cid = str(chat_id)
        cq: queue.Queue = queue.Queue()
        opts = [str(o) for o in (options or [])]
        self._clarify_pending[cid] = (cq, opts)
        msg = "❓ " + str(question)
        if opts:
            msg += "\n" + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
            msg += "\n" + _tr("gw.clarify_hint", _default="(reply with the number or the text)")
        try:
            self.channel.send(chat_id, msg)
        except Exception:  # noqa: BLE001 — falha de entrega não trava o turno (cai no timeout/None)
            pass
        try:
            ans = cq.get(timeout=self.clarify_timeout)
        except queue.Empty:
            ans = None
        finally:
            self._clarify_pending.pop(cid, None)
        return ans

    def _approve(self, chat_id, s: Session) -> Callable[[dict], bool]:
        def approve(req: dict) -> bool:
            if s.yolo or self.approval_mode == "yolo":     # YOLO explícito → autoaprova
                return True
            if self.approval_mode == "smart" and req.get("risk") == "low":
                return True
            _cat = req.get("category", "")
            if _cat and _cat in s.approved_cats:           # JÁ aprovado PRA SESSÃO (Hermes) → não pergunta de novo
                return True
            # SMART (item 13): juiz LLM auxiliar julga o comando flagrado. APPROVE auto-aprova a
            # sessão, DENY bloqueia, ESCALATE (e qualquer erro — fail-closed) cai no prompt humano.
            if self.approval_mode == "smart" and self.cfg is not None:
                verdict = smart_judge(self.cfg, req)
                if verdict == "approve":
                    if _cat:
                        s.approved_cats.add(_cat)
                    return True
                if verdict == "deny":
                    return False
                # escalate → segue pro fluxo humano abaixo
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
            ask = "⚠ " + _tr(
                "gw.approve_ask",
                _default="Approve [{tool}]{brief}\n{reason} (risk={risk})"
                         "\n/yes (once) · /always (allow '{cat}' for the whole session) · /no",
                tool=req.get("tool", "?"), brief=brief, reason=req["reason"],
                risk=req.get("risk", "?"), cat=_cat)
            if req.get("tool") in ("run_shell", "process_start"):   # destaca O QUE é arriscado (OpenClaw)
                from okami.core.approval import command_risks
                _risks = command_risks(str((req.get("args") or {}).get("cmd", "")))
                if _risks:
                    ask += "\n" + "\n".join(f"  ‼ {r}" for r in _risks[:5])
            _sa = getattr(self.channel, "send_approval", None)   # botões inline se o canal suportar
            if _sa:
                try:
                    _sa(chat_id, ask, nonce=nonce)
                except TypeError:                        # canal sem suporte a nonce → compat
                    _sa(chat_id, ask)
            else:
                self.channel.send(chat_id, ask)
            try:
                ans = q.get(timeout=self.approval_timeout)
            except queue.Empty:
                ans = "/no"
                self.approvals.expire_if_pending(nonce)  # sem resposta → marca expirado no registro
            finally:
                self._pending.pop(str(chat_id), None)
            verb = ans.strip().lower()
            always = verb in ("/always", "/sempre", "/sessao", "/sessão", "always", "sempre")
            ok = always or verb in ("/yes", "yes", "sim", "y", "ok")
            if always and _cat:                          # aprova a CATEGORIA pra sessão toda (não pergunta mais)
                s.approved_cats.add(_cat)
                self._save_meta(chat_id, s)
                self.channel.send(chat_id, "✅ " + _tr(
                    "gw.approved_category",
                    _default="approved · '{cat}' allowed for this session (won't ask again)", cat=_cat))
            else:
                self.channel.send(chat_id, "✅ " + _tr("gw.approved", _default="approved") if ok
                                  else "❌ " + _tr("gw.denied", _default="denied"))
            return ok
        return approve

    def handle(self, chat_id, text: str, surface_override: str | None = None) -> None:
        # `surface_override` (#13): força a tool policy de uma superfície ESPECÍFICA neste turno, em vez
        # de herdar a do canal-base (self.surface). É per-chamada (NÃO muta self.surface → thread-safe vs.
        # o poll concorrente do canal-base) e propaga no spawn do _run. Usado pelo webhook: o evento roda
        # sob 'webhook' (deny-by-default de shell), não sob 'telegram' com os grants do dono.
        # DENY-BY-DEFAULT + PAREAMENTO: o allowlist do canal (agent.yaml) OU a aprovação dinâmica
        # (PairingStore) abrem o chat. Não-autorizado recebe um CÓDIGO p/ o dono aprovar pelo CLI —
        # em vez do "🚫 não autorizado" seco que deixava o bot mudo até editar config na mão.
        if not (self.channel.allowed(chat_id) or self._pairing.is_approved(chat_id)):
            if self.surface in _REMOTE_SURFACES:         # canal remoto → pareamento (dono aprova pelo CLI)
                self._emit_pairing_prompt(chat_id)
            else:                                        # CLI/terminal: a pessoa já é o dono → recusa seca
                self.channel.send(chat_id, "🚫 " + _tr("gw.chat_unauthorized", _default="chat not authorized."))
            return
        self._last_chat = str(chat_id)                 # alvo do notify_on_complete (#1/#8) best-effort
        text = (text or "").strip()
        cid = str(chat_id)
        if cid in self._pending:                       # resposta a uma aprovação pendente
            pend = self._pending[cid]
            q, want = pend if isinstance(pend, tuple) else (pend, "")   # tolera fila pura (compat)
            verb, _, got = text.partition(":")         # "/yes" | "/yes:<nonce>" (botão)
            if got and want and got != want:           # nonce velho/errado = clique stale → IGNORA
                self.channel.send(chat_id, "⌛ " + _tr(
                    "gw.button_expired",
                    _default="that button expired (another action happened). Use /yes or /no."))
                return
            store = getattr(self, "approvals", None)   # ausente em endpoint bare (alguns testes/compat)
            if want and store is not None:             # #7: consome o registro durável (single-use + expiração)
                _ap = ("/yes", "yes", "sim", "y", "ok", "/always", "/sempre", "/sessao", "/sessão", "always", "sempre")
                decision = "approved" if verb.strip().lower() in _ap else "denied"
                res = store.consume(want, decision)
                if not res.ok and res.reason != "desconhecido":   # já usado / expirado → recusa (não re-executa)
                    self.channel.send(chat_id, "⌛ " + _tr(
                        "gw.approval_invalid",
                        _default="invalid approval ({reason}). Use /yes or /no again.", reason=res.reason))
                    return
            q.put(verb)
            return
        if text.partition(":")[0].lower() in ("/yes", "/no", "/always", "/sempre"):   # aprovação sem nada pendente
            self.channel.send(chat_id, _tr("gw.nothing_to_approve", _default="nothing pending to approve right now."))
            return
        if cid in self._clarify_pending:               # resposta a um clarify pendente (#8 item 1)
            cq, copts = self._clarify_pending[cid]
            ans = text.strip()
            if copts and ans.isdigit():                # número → mapeia p/ a opção do menu
                i = int(ans) - 1
                if 0 <= i < len(copts):
                    ans = copts[i]
            cq.put(ans)
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
                hint = ((" " + _tr("gw.did_you_mean", _default="Did you mean")
                         + " " + ", ".join("/" + x for x in sg) + "?") if sg
                        else " — " + _tr("gw.commands_lists_all", _default="/commands lists everything."))
                self.channel.send(chat_id, "❓ " + _tr(
                    "gw.unknown_command", _default="unknown command: {tok}.", tok=tok) + hint)
                return
            text = "/" + cdef.name + text[len(tok):]       # reescreve pro canônico → as branches casam
            low = text.lower()
        if low in ("/start", "/help", ""):
            self.channel.send(chat_id, self._help())
            return
        if low in ("/new", "/reset"):
            s.history.clear()
            s.approved_cats.clear()                    # sessão nova → zera as aprovações de /always
            self.store.reset(chat_id)                  # arquiva o transcript e zera a contagem
            self.channel.send(chat_id, "🧹 " + _tr("gw.conversation_reset", _default="conversation reset."))
            return
        if low == "/status":
            bg = (" · ▶" + _tr("gw.status_background", _default="{n} background", n=len(self._bg))) if self._bg else ""
            q = (" · 🕓" + _tr("gw.status_queue", _default="{n} queued", n=len(s.queued))) if s.queued else ""
            ttl = f" · 📝 {s.title}" if s.title else ""
            mute = " · 🔇" if s.voice_off else ""
            _turns = int(self.store.entry(chat_id).get("node_count", 0)) // 2 or len(s.history) // 2
            state = (_tr("gw.status_busy", _default="busy") if s.busy
                     else _tr("gw.status_free", _default="free"))
            self.channel.send(chat_id, _tr(
                "gw.status_line",
                _default="agent {agent}{ttl} · {state} · {turns} exchanges · yolo={yolo}",
                agent=self.agent_id, ttl=ttl, state=state, turns=_turns,
                yolo=("on" if s.yolo else "off")) + f"{mute}{bg}{q}")
            return
        if low == "/yolo":
            s.yolo = True
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "⚡ " + _tr(
                "gw.yolo_on", _default="YOLO on (auto-approves in this session)."))
            return
        if low == "/normal":
            s.yolo = False
            _had = len(s.approved_cats)
            s.approved_cats.clear()                      # revoga as aprovações de sessão (/always) também
            self._save_meta(chat_id, s)
            extra = (" " + _tr("gw.normal_revoked",
                               _default="({n} session approval(s) revoked)", n=_had)) if _had else ""
            self.channel.send(chat_id, "🔒 " + _tr("gw.normal", _default="normal approval.") + extra)
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
            self.channel.send(chat_id, "🔈 " + _tr("gw.voice_off", _default="audio OFF in this session.")
                              if s.voice_off
                              else "🔊 " + _tr("gw.voice_on",
                                               _default="audio ON (I reply by voice when TTS is active)."))
            return
        if low.startswith("/busy"):
            arg = text[len("/busy"):].strip().lower()
            if arg in ("queue", "fila"):
                s.busy_mode = "queue"
            elif arg in ("interrupt", "corta", "stop"):
                s.busy_mode = "interrupt"
            elif arg in ("", "status"):
                q = (" · " + _tr("gw.busy_queued_count", _default="{n} in queue", n=len(s.queued))) if s.queued else ""
                self.channel.send(chat_id, "⏳ " + _tr(
                    "gw.busy_status", _default="busy mode: {mode}", mode=s.busy_mode) + q
                    + ". " + _tr("gw.busy_options", _default="Options: queue · interrupt."))
                return
            else:
                self.channel.send(chat_id, _tr(
                    "gw.busy_usage",
                    _default="usage: /busy queue (queue) | interrupt (cuts the current one) | status"))
                return
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "⏳ " + _tr("gw.busy_set", _default="busy → {mode}.", mode=s.busy_mode))
            return
        if low in ("/reload", "/reloadconfig"):        # #12: hot-reload de config (sem reiniciar)
            ok, msg = self.reload_config()
            self.channel.send(chat_id, "🔄 " + _tr("gw.config_reloaded", _default="config reloaded — {msg}", msg=msg)
                              if ok else "✗ " + _tr("gw.config_invalid", _default="invalid config: {msg}", msg=msg))
            return
        if low == "/restart":                          # reinicia o gateway DO CHAT (Hermes /restart):
            from okami.gateway import restart as _rst  # código/config novos sem ir ao terminal
            ok, msg = _rst.schedule_self_restart()
            self.channel.send(chat_id, ("🔄 " if ok else "✗ ") + msg)
            return
        if low.startswith("/memory"):                  # fila de aprovação de escrita (write_approval)
            from okami.memory.staging import PendingStore
            st = PendingStore(self.home or self.ws)
            parts = text.split()
            sub = parts[1].lower() if len(parts) > 1 else "pending"
            which = parts[2] if len(parts) > 2 else "all"
            if sub in ("approve", "aprovar"):
                n = st.approve(which)
                self.channel.send(chat_id, f"✓ {n} escrita(s) de memória aprovada(s) e aplicada(s).")
            elif sub in ("reject", "rejeitar"):
                n = st.reject(which)
                self.channel.send(chat_id, f"✗ {n} escrita(s) descartada(s).")
            else:                                      # pending (default)
                items = st.pending()
                if not items:
                    self.channel.send(chat_id, "(nada pendente — a fila de memória está vazia)")
                else:
                    lines = [f"• {i['id']} [{i['kind']}] {i['text'][:120]}" for i in items]
                    self.channel.send(chat_id, "Escritas de memória aguardando aprovação:\n" +
                                      "\n".join(lines) +
                                      "\n\n/memory approve <id|all> · /memory reject <id|all>")
            return
        if low.startswith("/goal"):                    # objetivo PERSISTENTE do chat (item 41)
            arg = text[len("/goal"):].strip()
            if not arg:
                self.channel.send(chat_id, "🎯 " + self._goals.status_text(chat_id))
            elif arg.lower() in ("clear", "off", "limpar"):
                self._goals.clear(chat_id)
                self.channel.send(chat_id, "🎯 " + _tr("gw.goal_cleared", _default="goal cleared."))
            elif arg.lower() in ("done", "concluido", "concluído"):
                self._goals.mark_done(chat_id)
                self.channel.send(chat_id, "🎯 ✅ " + _tr("gw.goal_done", _default="goal marked as done."))
            else:
                self._goals.set_goal(chat_id, arg)
                self.channel.send(chat_id, "🎯 " + _tr(
                    "gw.goal_set",
                    _default="goal set: {goal}. It persists across turns; add steps with /subgoal "
                             "<text>; /goal shows status.", goal=arg))
            return
        if low.startswith("/subgoal"):
            arg = text[len("/subgoal"):].strip()
            if not arg:
                self.channel.send(chat_id, "🎯 " + self._goals.status_text(chat_id))
                return
            if self._goals.add_subgoal(chat_id, arg) is None:
                self.channel.send(chat_id, _tr(
                    "gw.subgoal_no_goal", _default="no active goal — set one first: /goal <text>"))
            else:
                self.channel.send(chat_id, "🎯 ◻ " + _tr(
                    "gw.subgoal_added", _default="subgoal added: {sub}", sub=arg))
            return
        if low == "/stop":
            s.cancel = True
            self.channel.send(chat_id, "⏹ " + _tr("gw.stopping", _default="stopping after the current step…"))
            return
        if low in ("/retry", "/continuar"):            # retoma a última tarefa que ficou sem resposta
            if s.busy:
                self.channel.send(chat_id, "⏳ " + _tr("gw.already_processing", _default="already processing."))
                return
            if not s.interrupted():
                self.channel.send(chat_id, _tr("gw.nothing_to_resume", _default="nothing interrupted to resume."))
                return
            last = s.history[-1][1]                     # o USER pendente continua; _run não re-adiciona
            s.busy, s.cancel = True, False
            self._spawn(lambda: self._run(chat_id, last, s, resume=True))
            return
        if low.startswith("/feedback"):                # molda a identidade (§8), com go/no-go
            note = text[len("/feedback"):].strip()
            if not note:
                self.channel.send(chat_id, _tr(
                    "gw.feedback_usage", _default="usage: /feedback <how I should behave/speak>"))
                return
            self._evolve(chat_id, note)                   # explícito → aplica na hora (auto)
            return
        if low in ("/undo", "/rollback"):              # reverte a última evolução de identidade
            from okami.learning import persona
            removed = persona.rollback(self.ws, 1)
            self.channel.send(chat_id, ("↩ " + _tr("gw.reverted", _default="reverted: {text}",
                                                   text=removed[0].get("text")) if removed
                                        else _tr("gw.nothing_to_revert", _default="nothing to revert.")))
            return
        cmd0 = low.split(maxsplit=1)[0]
        if cmd0 in ("/like", "/dislike", "/different"):   # taste de design (§9): aprende o gosto
            from okami.learning import taste
            verdict = {"/like": "approved", "/dislike": "rejected", "/different": "want_different"}[cmd0]
            desc = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if not desc:
                self.channel.send(chat_id, _tr(
                    "gw.taste_usage",
                    _default="usage: {cmd} <what you thought of the design (e.g. 'bootstrap, neon')>", cmd=cmd0))
                return
            prof = taste.record_feedback(self.ws, verdict, desc)
            self.channel.send(chat_id, "🎨 " + _tr(
                "gw.taste_noted", _default="noted your taste (likes={attracts}, dislikes={repels}).",
                attracts=len(prof.attractors), repels=len(prof.repulsors)))
            return
        if low.startswith("/think"):                   # esforço de raciocínio desta sessão (gpt-5/codex)
            arg = text[len("/think"):].strip().lower()
            if arg in ("", "off", "auto", "default"):
                s.reasoning_effort = ""
                self.channel.send(chat_id, "🧠 " + _tr(
                    "gw.think_default",
                    _default="think at the model default. Levels: minimal·low·medium·high."))
            else:
                s.reasoning_effort = arg
                self.channel.send(chat_id, "🧠 " + _tr(
                    "gw.think_set", _default="think = {arg} (applies in this session).", arg=arg))
            self._save_meta(chat_id, s)
            return
        if low.startswith("/persona"):                 # overlay TEMPORÁRIO de sessão (estilo /personality)
            from okami.learning import persona
            arg = text[len("/persona"):].strip()
            if arg.lower() in ("", "off", "reset", "normal"):
                s.persona_overlay = ""
                self.channel.send(chat_id, "🎭 " + _tr("gw.persona_default", _default="default persona. Presets: ")
                                  + ", ".join(persona.PERSONA_PRESETS))
            else:
                s.persona_overlay = persona.overlay(arg)
                self.channel.send(chat_id, "🎭 " + _tr(
                    "gw.persona_set", _default="this session: {arg} (/persona off to go back)", arg=arg))
            self._save_meta(chat_id, s)
            return
        if low == "/sethome":                           # destino dos lembretes/cron sem alvo explícito
            self.set_home(chat_id)
            self.channel.send(chat_id, "🏠 " + _tr(
                "gw.sethome",
                _default="this chat is now HOME for reminders/schedules with no explicit target."))
            return
        if low.startswith("/topic"):                    # tópicos do Telegram já viram sessões separadas (auto)
            cur = ":" in cid and cid.rsplit(":", 1)[1]
            here = ("\n" + _tr("gw.topic_here",
                                _default="You're in topic {cur} (separate conversation).", cur=cur)) if cur else ""
            self.channel.send(chat_id, "🧵 " + _tr(
                "gw.topic_info",
                _default="each Telegram TOPIC in this chat is a separate conversation "
                         "(its own history/session) — automatic. Create a topic in the app to open "
                         "another parallel conversation thread.") + here)
            return
        if low == "/commands":                          # registry: lista completa por categoria
            self.channel.send(chat_id, self._commands_text())
            return
        if low == "/usage":
            self.channel.send(chat_id, self._usage_text(chat_id))
            return
        if low.startswith("/platform"):              # circuit breaker por plataforma (item 23)
            parts = text.split()
            sub = parts[1].lower() if len(parts) > 1 else "list"
            who = parts[2] if len(parts) > 2 else self.surface
            if sub in ("pause", "pausar"):
                self._breaker.pause(who)
                self.channel.send(chat_id, f"⏸ plataforma '{who}' pausada (não vou pollar até /platform resume).")
            elif sub in ("resume", "retomar"):
                self._breaker.resume(who)
                self.channel.send(chat_id, f"▶ plataforma '{who}' retomada.")
            else:                                    # list (default)
                st = self._breaker.status()
                if not st:
                    self.channel.send(chat_id, f"📡 plataforma atual: {self.surface} · ok (nenhuma falha).")
                else:
                    icon = {"ok": "✓", "backoff": "⚠", "paused": "⏸"}
                    lines = [f"{icon.get(s['state'], '?')} {s['name']}: {s['state']}"
                             + (f" (retry {s['retry_in']}s, {s['fails']} falhas)" if s["state"] == "backoff" else "")
                             for s in st]
                    self.channel.send(chat_id, "📡 plataformas:\n" + "\n".join(lines))
            return
        if low.startswith("/insights"):              # analytics histórico cross-sessão (item 21)
            arg = text[len("/insights"):].strip()
            try:
                days = int(arg) if arg else 30
            except ValueError:
                days = 30
            from okami.observability import insights
            self.channel.send(chat_id, insights.render(insights.collect(self.ws, days=days)))
            return
        if low == "/tools":
            self.channel.send(chat_id, self._tools_text())
            return
        if low == "/config":
            self.channel.send(chat_id, self._config_text())
            return
        if low == "/whoami":
            self.channel.send(chat_id, "🪪 " + _tr(
                "gw.whoami", _default="chat id: {chat_id} · agent: {agent}",
                chat_id=chat_id, agent=self.agent_id))
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
                self.channel.send(chat_id, "📝 " + _tr("gw.title_current", _default="title: {title}", title=s.title)
                                  if s.title
                                  else _tr("gw.title_none", _default="no title. Usage: /title <name>"))
                return
            s.title = arg[:80]
            self._save_meta(chat_id, s)
            self.channel.send(chat_id, "📝 " + _tr(
                "gw.title_renamed", _default="conversation renamed: {title}", title=s.title))
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
                self.channel.send(chat_id, _tr(
                    "gw.background_usage",
                    _default="usage: /background <task> · /background --process <cmd> "
                             "(server/build) · /background status · /background log <id> · "
                             "/background cancel <id>. I run it in parallel and report when done."))
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
                self.channel.send(chat_id, _tr(
                    "gw.process_usage",
                    _default="usage: /process status · /process log <id> [lines] · "
                             "/process kill <id> · /process signal <id> <SIGNAL>. (immediate, real kill)"))
            return
        from okami.automation.scheduler import Scheduler, infer_commitment   # §11: "me lembra de X amanhã" → agenda
        ic = infer_commitment(text, time.time())
        if ic:
            schedule, prompt = ic
            job = Scheduler(".").add(schedule, prompt, agent=self.agent_id, target=str(chat_id))
            self.channel.send(chat_id, "⏰ " + _tr(
                "gw.scheduled", _default="scheduled [{schedule}]: {prompt}",
                schedule=job["schedule"], prompt=prompt))
            return
        with self._sess_lock:                           # check-then-set ATÔMICO vs. o drain do finally (race)
            if s.busy:                                   # ocupado: enfileira (e corta a atual se modo interrupt)
                s.queued.append((text, self._img.pop(cid, None)))
                decision, qn = ("interrupt" if s.busy_mode == "interrupt" else "queued"), len(s.queued)
                if decision == "interrupt":
                    s.cancel = True
            else:
                s.busy, s.cancel, decision = True, False, "start"
        if decision == "start":                          # efeitos colaterais (send/spawn) FORA do lock
            self._spawn(lambda: self._run(chat_id, text, s, images=self._img.pop(cid, None),
                                          surface_override=surface_override))
        elif decision == "interrupt":
            self.channel.send(chat_id, "⏹ " + _tr(
                "gw.interrupting", _default="interrupting the current one — starting your new message now."))
        else:
            self.channel.send(chat_id, "⏳ " + _tr(
                "gw.queued", _default="queued (#{n}) — I'll start when the current one finishes.", n=qn))

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
        u = CanonicalUsage.from_dict((stats or {}).get("usage") or {})
        try:                                              # ctx %: quão cheia está a janela do modelo —
            pc = self.cfg.provider() if self.cfg else None  # tokens de ENTRADA (prompt inteiro: sistema +
            if pc and u.input_tokens:                       # memória + skills + histórico + saídas de tool)
                from okami.llm.providers import context_window_tokens   # ÷ janela do modelo. NÃO o char-sum
                win = max(1, context_window_tokens(pc))                 # do histórico (que dava ~0%).
                parts.append(f"ctx {min(100, round(100 * u.input_tokens / win))}%")
        except Exception:  # noqa: BLE001 — footer é cosmético, nunca quebra o turno
            pass
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
        out = ["⚙ " + _tr("gw.processes_header",
                           _default="processes (real OS — immediate kill: /process kill <id>):")]
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
            out.append("⏳ " + _tr("gw.bgstatus_queue",
                                   _default="this session's queue: {n} waiting", n=queued))
        if jobs:
            icon = {"running": "▶", "done": "✅", "failed": "❌", "interrupted": "⏸", "cancelled": "⏹"}
            out.append("📋 " + _tr("gw.bgstatus_jobs_header",
                                   _default="/background tasks (durable — survives restart):"))
            for j in jobs:
                when = (_dt.datetime.fromtimestamp(j["started_at"]).strftime("%d/%m %H:%M")
                        if j.get("started_at") else "?")
                out.append(f"  {icon.get(j.get('state'), '·')} #{j['id']} [{when}] {(j.get('prompt') or '')[:60]}")
        else:
            out.append("▶ " + _tr("gw.bgstatus_none", _default="no /background tasks yet."))
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
            return _tr(
                "gw.bgproc_usage",
                _default="usage: /background --process <command> (e.g. npm run dev) — runs as an OS PROCESS, "
                         "with a REAL kill (/process kill <id>) and paginated log (/process log <id>).")
        from okami.core.approval import classify
        sens = classify("process_start", {"cmd": cmd})
        if sens and not yolo:                            # destrutivo/sensível sem yolo → NEGA
            return "🚫 " + _tr(
                "gw.bgproc_refused",
                _default="refused: {reason} (risk {risk}). A sensitive command straight from the chat only "
                         "with /yolo in this session — or ask ME to run it (then it goes through go/no-go).",
                reason=sens.reason, risk=sens.risk)
        try:
            from okami.core.sandbox import SandboxPolicy
            pol = SandboxPolicy.from_config((self.cfg.sandbox if self.cfg else None) or {})
        except Exception:  # noqa: BLE001
            pol = None
        try:
            meta = self._pm().start(cmd, pol, notify=True)   # notify → aviso quando terminar
        except ValueError as e:                          # sandbox bloqueou (sensível/docker exigido)
            return "✗ " + _tr("gw.bgproc_no_start", _default="didn't start: {e}", e=e)
        except Exception as e:  # noqa: BLE001
            return "✗ " + _tr("gw.bgproc_start_fail", _default="failed to start the process: {e}", e=e)
        return "⚙ " + _tr(
            "gw.bgproc_up",
            _default="process {pid_id} up (PID {pid}) — real kill: /process kill {pid_id} · "
                     "log: /process log {pid_id}. I'll let you know when it finishes.",
            pid_id=meta["id"], pid=meta["pid"])

    def _process_status(self) -> str:
        try:
            procs = self._pm().list()
        except Exception:  # noqa: BLE001
            procs = []
        if not procs:
            return "⚙ " + _tr(
                "gw.process_none",
                _default="no OS processes right now. Long servers/builds the agent starts (process_start) "
                         "show up here — with immediate kill (/process kill <id>), unlike the cooperative background.")
        return self._fmt_processes(procs)

    def _process_log(self, arg: str) -> str:
        """/process log <id> [linhas] [offset]. Sem offset = ÚLTIMAS N linhas; com offset = a partir dela.
        Mostra a faixa (X–Y de Z) e um link explícito p/ a PRÓXIMA página."""
        toks = arg.split()
        if not toks:
            return _tr(
                "gw.proclog_usage",
                _default="usage: /process log <id> [lines] [offset]. E.g. /process log ab12 40 0 (from the start).")
        pid = toks[0]
        n = int(toks[1]) if len(toks) > 1 and toks[1].lstrip("-").isdigit() else 30
        explicit = len(toks) > 2 and toks[2].lstrip("-").isdigit()
        offset = int(toks[2]) if explicit else -n        # default: as últimas N linhas
        page = self._pm().log_page(pid, offset=offset, limit=n)
        if not page["lines"]:
            return "📄 " + _tr(
                "gw.proclog_empty", _default="process {pid}: no log in that range (or id doesn't exist).", pid=pid)
        start, end, total = page["offset"] + 1, page["offset"] + page["shown"], page["total"]
        out = ["📄 " + _tr(
            "gw.proclog_header", _default="process {pid} — lines {start}–{end} of {total}:",
            pid=pid, start=start, end=end, total=total)]
        out += ["  " + ln for ln in page["lines"]]
        if end < total:                                  # próxima página explícita
            out.append(_tr(
                "gw.proclog_more", _default="… +{rest} more line(s): /process log {pid} {n} {end}",
                rest=total - end, pid=pid, n=n, end=end))
        return "\n".join(out)

    def _process_kill(self, arg: str) -> str:
        toks = arg.split()
        if not toks:
            return _tr("gw.prockill_usage", _default="usage: /process kill <id> (ids in /process status).")
        pid = toks[0]
        if self._pm().poll(pid).get("status") == "unknown":
            return "✗ " + _tr(
                "gw.prockill_unknown", _default="process {pid} doesn't exist (see /process status).", pid=pid)
        ok = self._pm().kill(pid)
        return ("🛑 " + _tr("gw.prockill_done", _default="process {pid} killed (SIGTERM on the group).", pid=pid)
                if ok else "✗ " + _tr("gw.prockill_fail", _default="couldn't kill {pid}.", pid=pid))

    def _process_signal(self, arg: str) -> str:
        toks = arg.split()
        if len(toks) < 2:
            return _tr(
                "gw.procsig_usage",
                _default="usage: /process signal <id> <SIGNAL> (e.g. HUP, KILL, USR1, STOP, CONT).")
        pid, name = toks[0], toks[1].upper().lstrip("SIG")
        ok = self._pm().signal(pid, name)
        return ("📶 " + _tr("gw.procsig_sent", _default="signal {name} → {pid}.", name=name, pid=pid)
                if ok else "✗ " + _tr(
                    "gw.procsig_fail", _default="couldn't signal {pid} (invalid id/signal?).", pid=pid))

    def _background_log(self, arg: str) -> str:
        toks = arg.split()
        if not toks or not toks[0].lstrip("#").isdigit():
            return _tr("gw.bglog_usage", _default="usage: /background log <id> [lines] (ids in /background status).")
        bid = int(toks[0].lstrip("#"))
        n = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else 30
        lines = self._bgreg.tail(bid, n)
        if not lines:
            return "📄 " + _tr(
                "gw.bglog_empty", _default="background #{bid}: no log yet (or id doesn't exist).", bid=bid)
        return "📄 " + _tr(
            "gw.bglog_header", _default="background #{bid} (last {n} lines):", bid=bid, n=len(lines)) \
            + "\n" + "\n".join("  " + ln for ln in lines)

    def _background_cancel(self, arg: str) -> str:
        a = arg.lstrip("#").strip()
        if not a.isdigit():
            return _tr(
                "gw.bgcancel_usage",
                _default="usage: /background cancel <id> (see ids in /background status).")
        bid = int(a)
        ev = self._bg_cancel.get(bid)
        if ev is None:
            return "✗ " + _tr(
                "gw.bgcancel_not_running",
                _default="background #{bid} isn't running now (already finished, was cancelled, or belonged to "
                         "another session/process). See /background status.", bid=bid)
        ev.set()
        return "⏹ " + _tr(
            "gw.bgcancel_cancelling",
            _default="cancelling background #{bid} — stops at the next step (cooperative). If it started a "
                     "server/build, see /process status and kill it now with /process kill <id>.", bid=bid)

    def _spawn_background(self, chat_id, prompt: str, *, yolo: bool = False) -> None:
        """/background: roda `prompt` numa tarefa ISOLADA (não toca no histórico da sessão), em paralelo,
        e devolve o resultado quando terminar. Aprovação fail-closed (só ações seguras) a menos que a
        sessão esteja em yolo — em background não dá pra pedir /yes interativo."""
        bid = self._bgreg.add(prompt)                    # PERSISTE (durável): id/prompt/estado/tempos
        ev = threading.Event()                           # sinal de cancelamento cooperativo (como o /stop)
        self._bg_cancel[bid] = ev
        self._bg[bid] = prompt[:60]
        self.channel.send(chat_id, "▶ " + _tr(
            "gw.bg_running",
            _default="background #{bid} running — I stay free to chat; I'll report when done. "
                     "(/background cancel {bid} to stop)", bid=bid))

        from okami.gateway.background import event_line_plain

        def _on_ev(e, _bid=bid):                         # stream AO VIVO: cada passo do harness → log do job
            self._bgreg.append_log(_bid, event_line_plain(e))

        def _bgrun(_bid=bid, _p=prompt, _yolo=yolo, _ev=ev):
            try:
                approve = (lambda req: True) if _yolo else (lambda req: False)   # fail-closed sem interação
                task = self.run_task(self.cfg, self.ws, _p, approve=approve, surface=self.surface,
                                     agent_home=self.home, open_fs=self.open_fs,   # casa isolada + acesso (CLI)
                                     allow_paths=self.allow_paths,   # pastas extras liberadas (config)
                                     cancel=_ev.is_set,   # harness checa entre passos → para no /background cancel
                                     on_event=_on_ev)     # progresso ao vivo → /background log <id>
                if _ev.is_set():
                    self._bgreg.append_log(_bid, "⏹ " + _tr("gw.bg_log_cancelled", _default="cancelled"))
                    self._bgreg.finish(_bid, state="cancelled",
                                       result=_tr("gw.bg_cancelled_by_user", _default="cancelled by the user"))
                    self.channel.send(chat_id, "⏹ " + _tr(
                        "gw.bg_cancelled", _default="background #{bid} cancelled.", bid=_bid))
                else:
                    out = (getattr(task, "result", "") or "").strip() or _tr(
                        "gw.bg_no_output", _default="(no textual output)")
                    self._bgreg.append_log(_bid, "✅ " + _tr("gw.bg_log_done", _default="done"))
                    self._bgreg.finish(_bid, state="done", result=out)
                    self.channel.send(chat_id, "✅ " + _tr(
                        "gw.bg_done", _default="background #{bid} ready:", bid=_bid) + "\n" + out)
            except Exception as e:  # noqa: BLE001 — background nunca derruba o endpoint
                self._bgreg.append_log(_bid, "❌ " + _tr("gw.bg_log_error", _default="error: {e}", e=e))
                self._bgreg.finish(_bid, state="failed", result=str(e))
                self.channel.send(chat_id, "❌ " + _tr(
                    "gw.bg_failed", _default="background #{bid} failed: {e}", bid=_bid, e=e))
            finally:
                self._bg.pop(_bid, None)
                self._bg_cancel.pop(_bid, None)

        self._spawn(_bgrun)

    def _goal_after_turn(self, chat_id, reply: str) -> None:
        """Pós-turno do objetivo persistente (item 41): conta o turno, roda o juiz auxiliar (fail-open)
        e avisa o chat de subgoal fechado / objetivo concluído / orçamento esgotado. Best-effort."""
        try:
            g = self._goals.get(chat_id)
            if not g or g.get("done"):
                return
            self._goals.bump_turn(chat_id)
            from okami.gateway.goals import judge_turn
            verdict = judge_turn(self.cfg, self._goals, chat_id, reply)
            for idx in verdict["completed"]:
                sub = self._goals.get(chat_id)["subgoals"][idx]
                self.channel.send(chat_id, f"🎯 ✅ subgoal concluído: {sub['text']} — {sub['evidence'][:120]}")
            if verdict["goal_done"]:
                self.channel.send(chat_id, "🎯 🏁 objetivo CONCLUÍDO (todos os subgoals fechados). /goal clear remove.")
                return
            fresh = self._goals.get(chat_id)
            if fresh and not fresh.get("done") and fresh["turns_used"] >= fresh["turn_budget"]:
                self.channel.send(chat_id, "🎯 ⏸ orçamento de turnos do objetivo ESGOTADO "
                                           f"({fresh['turn_budget']}). Ele para de entrar no contexto — "
                                           "renove com /goal <texto> ou encerre com /goal clear.")
        except Exception:  # noqa: BLE001 — objetivo nunca quebra o turno
            from okami import log
            log.dbg("goal_after_turn falhou", exc_info=True)

    def _run(self, chat_id, text: str, s: Session, resume: bool = False, images=None,
             surface_override: str | None = None) -> None:
        if resume:                                        # retomada: o USER já está no transcript
            ctx = _history_block(s.history[:-1], max_chars=self.max_history_chars)
        else:
            ctx = _history_block(s.history, max_chars=self.max_history_chars)   # histórico PRIOR
            self._append_turn(chat_id, s, "USER", text)   # grava a fala EM ANDAMENTO (detecta interrupção)
        if s.persona_overlay:                              # overlay de sessão prevalece sobre o tom padrão
            ctx = s.persona_overlay + ("\n\n" + ctx if ctx else "")
        _goal_block = self._goals.context_block(chat_id)   # objetivo persistente (item 41) — referência
        if _goal_block:
            ctx = _goal_block + ("\n\n" + ctx if ctx else "")
        genesis = genesis_pending(self.ws)                 # 1ª config (§8.2): onboarding de primeiro contato
        if genesis:
            ctx = GENESIS_BLOCK + ("\n\n" + ctx if ctx else "")
        if getattr(self.channel, "supports_media", False):   # canal com anexo → agente sabe o MEDIA:<path>
            ctx = MEDIA_HINT + ("\n\n" + ctx if ctx else "")
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
        _thinking = "💭 " + _tr("gw.thinking", _default="{agent} is thinking…", agent=self.agent_id)
        _status_id = None                                # streaming-by-edit: 1 msg de status editada ao vivo
        if getattr(self.channel, "supports_edit", False):
            _status_id = self.channel.send_status(chat_id, _thinking)
        if _status_id is None:                           # canal sem edição → comportamento de sempre
            self.channel.send(chat_id, _thinking)
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
            if _status_id is not None:                    # streaming-by-edit: edita a msg de status ao vivo
                on_ev = self._status_on_event(chat_id, _status_id, _thinking, on_ev)
            kw = {"approve": approve, "extra_context": ctx, "cancel": lambda: s.cancel}
            if kw_pre:
                kw["prelearned_files"] = kw_pre
            if on_ev is not None:                         # progresso ao vivo (tool-calls, loop, compaction…)
                kw["on_event"] = on_ev
            if s.reasoning_effort:                        # /think desta sessão → vence o default do provider
                kw["reasoning_effort"] = s.reasoning_effort
            if s.provider_override:                       # /model <provider> → troca o provider da sessão (codex…)
                kw["provider"] = s.provider_override
            if s.model_override:                          # /model desta sessão → vence o default
                kw["model"] = s.model_override
            if images:                                    # vision (§6) só quando veio foto (compat c/ runners simples)
                kw["images"] = images
            kw.setdefault("surface", surface_override or self.surface)  # tool policy por superfície (P1.4);
            #                                              #13: surface_override força a da chamada (ex.: webhook)
            kw.setdefault("agent_home", self.home)         # casa isolada (memória/identidade ≠ projeto)
            kw.setdefault("open_fs", self.open_fs)         # acesso amplo no CLI; gateway confinado
            kw.setdefault("allow_paths", self.allow_paths) # pastas extras liberadas (config tools.allow_paths)
            # Entrega FORA-DO-TURNO (#7 item 3, usada por 10/14/19): o harness pode "tocar" o dono no meio
            # da tarefa (vigia/loop/lembrete) — entrega ao home_chat, redige segredo e (item 4) avisa o desktop.
            kw["notify"] = lambda m: self._notify_owner(chat_id, m)
            # PERGUNTA do agente ao dono (#8 item 1): bloqueia o turno até a resposta (vinda por handle()).
            kw["clarify"] = lambda q, opts, _cid=chat_id: self._ask_clarify(_cid, q, opts)
            # AMBIENTE REMOTO (SSH/Tailscale): rehidrata o alvo da sessão (multi-turno) + persiste mudanças.
            if s.remote_spec:
                from okami.integrations.remote import resolve_remote
                try:                                       # is_terminal=open_fs (fail-safe): gateway=False → allowlist
                    kw["remote"] = resolve_remote(getattr(self.cfg, "remote", None), s.remote_spec,
                                                  is_terminal=self.open_fs)
                except Exception:  # noqa: BLE001 — spec inválido (host saiu da allowlist) → volta ao local
                    s.remote_spec = None
            kw["set_remote"] = lambda rt, _s=s: setattr(_s, "remote_spec", getattr(rt, "alias", None) if rt else None)
            _t0 = time.time()                              # cronômetro da resposta (footer ctx·tok·tempo)
            task = self.run_task(self.cfg, self.ws, text, **kw)
            _elapsed = time.time() - _t0
            stats = getattr(task, "stats", None) or {}     # tokens do turno (custo §A5)
            if stats.get("usage"):
                try:
                    self.store.add_usage(chat_id, stats["usage"], served_by=stats.get("served_by", ""))
                    from okami.llm.usage import CanonicalUsage
                    _u = CanonicalUsage.from_dict(stats["usage"])
                    _pc = self.cfg.provider() if self.cfg else None
                    if _pc and _u.input_tokens:                # ctx% REAL = tokens de ENTRADA do último turno
                        from okami.llm.providers import context_window_tokens   # (prompt inteiro) ÷ janela do
                        _win = max(1, context_window_tokens(_pc))               # modelo — não o char-sum do
                        self.store.update_entry(chat_id, last_input_tokens=int(_u.input_tokens),  # histórico
                                                ctx_pct=min(100, round(100 * _u.input_tokens / _win)))
                except Exception:  # noqa: BLE001 — contabilidade nunca quebra o turno
                    pass
            reply = task.result or task.reason or f"({task.state.value})"
            if not task.result and task.state.name == "FAILED":   # #9: razão crua de erro de provider →
                from okami.gateway.response_filters import sanitize_provider_error   # categoria curta segura
                reply = sanitize_provider_error(reply)            # (não vaza HTTP body/request-id no chat)
            self._append_turn(chat_id, s, "AGENTE", reply)  # fecha o par → não é mais "interrompida"
            self._goal_after_turn(chat_id, reply)           # juiz do objetivo (fail-open, item 41)
            s.resume_attempts = 0                          # concluiu → zera a guarda de resume
            self._save_meta(chat_id, s)
            # Papo casual (respond puro, sem critério nem ação com efeito) NÃO leva prefixo robótico —
            # é conversa, não "tarefa concluída". Só decora quando houve trabalho de verdade.
            chatty = (task.state.name == "COMPLETE" and not task.exit_criteria
                      and not any(s.effect for s in task.steps))
            prefix = "" if chatty else {"COMPLETE": "✅ ", "BLOCKED": "⚠ ",
                                        "NEEDS_INPUT": "❓ "}.get(task.state.name, "❌ ")
            if task.state.name == "FAILED" and task.result:   # falhou MAS salvou entrega parcial → ⚠, não ❌ mudo
                prefix = "⚠ "
            reply_text, reply_media = reply, []
            if getattr(self.channel, "supports_media", False):   # MEDIA:<path> na resposta → anexo nativo
                from okami.channels.media import extract_media
                reply_text, reply_media = extract_media(reply)
            reply_text = redact(reply_text)                 # DLP de saída (#7 item 2): mascara segredo que o
            #                                                 modelo possa ter cuspido ANTES de qualquer send
            if reply_text.strip() or not reply_media:       # resposta só-anexo não manda texto vazio
                self.channel.send(chat_id, prefix + reply_text)
            for m in reply_media:
                try:
                    self.channel.send_media(chat_id, m.path, voice=m.voice, document=m.document)
                except Exception as me:  # noqa: BLE001 — anexo falhou → avisa com o caminho (não engole)
                    self.channel.send(chat_id, "⚠ " + _tr(
                        "gw.media_failed", _default="couldn't attach {path}: {e}", path=m.path, e=me))
            footer = self._turn_footer(s, stats, _elapsed)   # linha de custo: ctx · tokens · tempo
            if footer:
                self.channel.send(chat_id, footer)
            self._react(chat_id, {"COMPLETE": "👍", "BLOCKED": "👎",
                                  "NEEDS_INPUT": "🤔"}.get(task.state.name, "👎"))
            if _status_id is not None:                   # resolve a msg de status (não fica "💭 pensando")
                _done = {"COMPLETE": "✅", "BLOCKED": "⚠", "NEEDS_INPUT": "❓"}.get(task.state.name, "❌")
                self.channel.edit_message(chat_id, _status_id, _done + " " + _tr(
                    "gw.done", _default="done"))
            if not s.voice_off:                          # /voice off muta o áudio (TTS lê o texto LIMPO)
                self._maybe_voice(chat_id, reply_text or reply)
            self._observe(chat_id, text)                  # aprende o estilo do usuário (gradual, auto)
            self._observe_llm(chat_id, s)                 # a cada N turnos, leitura mais rica por LLM
            self._maybe_compact(chat_id)                  # transcript longo → nó SUMMARY (§6.4)
        except Exception as e:  # noqa: BLE001 — USER já está no transcript → detectável como interrompido
            # DLP de saída (#7 item 2): a mensagem de erro pode carregar um segredo (chave numa stacktrace,
            # token num traceback) → redige ANTES de mandar pro canal.
            self.channel.send(chat_id, "❌ " + redact(_tr("gw.run_error", _default="error: {e}", e=e)))
            self._react(chat_id, "👎")
        finally:
            with self._sess_lock:                        # reset+drain ATÔMICO vs. o check-then-set do dispatch
                s.busy = False
                s.cancel = False
                nxt = s.queued.pop(0) if s.queued else None
                if nxt is not None:                      # vai rodar a próxima da fila → segura o busy ligado
                    s.busy = True
            if nxt is not None:                          # spawn FORA do lock (não segura a trava no trabalho)
                nxt_text, nxt_img = nxt
                self._spawn(lambda t=nxt_text, im=nxt_img: self._run(  # #13: continuação herda a surface
                    chat_id, t, s, images=im, surface_override=surface_override))

    def _status_on_event(self, chat_id, status_id, header: str, base):
        """on_event que EDITA a msg de status ao vivo com o progresso (tool-calls), com throttle. Encadeia
        o on_event original (base) se houver. Best-effort — edição nunca quebra o turno."""
        import time as _t

        from okami.gateway.streamedit import StreamEditor
        from okami.tui import tool_emoji
        ed = StreamEditor(header=header)

        def _ev(e):
            if base is not None:
                try:
                    base(e)
                except Exception:  # noqa: BLE001
                    pass
            line = ""
            k = e.get("kind")
            if k == "step":
                line = f"{tool_emoji(e.get('tool', ''))} {e.get('tool', '')}"
            elif k == "loop":
                line = "🔁 ajustando a abordagem"
            elif k == "compact":
                line = "🗜️ compactando o contexto"
            elif k == "escalate":
                line = "🧠 escalando p/ modelo mais forte"
            if not line:
                return
            now = _t.monotonic()
            ed.feed(line, now=now)
            if ed.due(now):
                try:
                    self.channel.edit_message(chat_id, status_id, ed.render())
                    ed.mark_sent(now)
                except Exception:  # noqa: BLE001
                    pass

        _ev._status_id = status_id        # expõe o id p/ a finalização editar pro estado terminal
        return _ev

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

    def _inbox_file(self, path, name: str | None = None) -> str:
        """Copia um arquivo recebido pro inbox/ do workspace (nome original legível) e devolve
        o caminho relativo — o agente acessa direto, sem depender do temp do canal."""
        import shutil
        inbox = Path(self.ws) / "inbox"
        try:
            inbox.mkdir(parents=True, exist_ok=True)
            dst = inbox / (name or Path(path).name)
            shutil.copy(path, dst)
            return f"inbox/{dst.name}"
        except Exception:  # noqa: BLE001 — sem inbox → entrega o caminho do temp mesmo
            return str(path)

    def poll_once(self) -> None:
        fresh = []
        for msg in self.channel.poll():
            mid = getattr(msg, "msg_id", "")
            if mid:                                        # idempotência por turno (#3): entrega duplicada → ignora
                if mid in self._seen_msgs:
                    continue
                self._seen_msgs[mid] = True
                if len(self._seen_msgs) > 1000:            # LRU simples (descarta o mais antigo)
                    self._seen_msgs.popitem(last=False)
                self._last_msg_id[str(msg.chat_id)] = mid  # alvo das reações 👀/👍/👎
            fresh.append(msg)
        from okami.gateway.coalesce import coalesce_inbound
        for msg in coalesce_inbound(fresh):                # rajada do MESMO chat no lote → 1 turno
            text = msg.text
            if msg.audio and self.stt:                 # nota de voz → transcreve (Whisper)
                try:
                    text = self.stt.transcribe(msg.audio)
                    self.channel.send(msg.chat_id, "🎤 " + _tr("gw.heard", _default="heard: «{text}»", text=text))
                except Exception as e:  # noqa: BLE001
                    self.channel.send(msg.chat_id, "❌ " + _tr(
                        "gw.audio_unclear", _default="couldn't understand the audio: {e}", e=e))
                    continue
            if getattr(msg, "image", None):            # foto → vision (§6)
                self._img[str(msg.chat_id)] = msg.image
                self.handle(msg.chat_id, text or "Analise a imagem que enviei.")
                continue
            if getattr(msg, "file", None):             # documento/vídeo → inbox do workspace + nota
                rel = self._inbox_file(msg.file, getattr(msg, "file_name", "") or None)
                note = _tr("gw.file_received",
                           _default="[the user sent a file: `{rel}` — saved in the workspace]", rel=rel)
                self.handle(msg.chat_id, f"{text}\n\n{note}" if text else note)
                continue
            if text:
                # Compreensão de links (#7 item 11): mensagem que é SÓ uma URL (não-comando) → resume na
                # hora SEM gastar um turno LLM (sem run_task). Idempotente via _seen_msgs (dedup no topo).
                if self._link_understanding_enabled() and self._maybe_summarize_link(msg.chat_id, text):
                    continue
                self.handle(msg.chat_id, text)
        self._notify_completed_processes()

    def _link_understanding_enabled(self) -> bool:
        """True se channels.link_understanding está ligado na config (fail-open p/ dict/objeto/None)."""
        cfg = getattr(self, "cfg", None)              # paths sem init completo (testes/bare) não têm cfg
        ch = getattr(cfg, "channels", None)
        if ch is None and isinstance(cfg, dict):
            ch = cfg.get("channels")
        if isinstance(ch, dict):
            return bool(ch.get("link_understanding"))
        return bool(getattr(ch, "link_understanding", False))

    def _maybe_summarize_link(self, chat_id, text: str) -> bool:
        """Se `text` é só uma URL, abre + resume (modelo auxiliar, SSRF guardado no web_extract) e entrega
        direto — SEM run_task (sem turno LLM). Devolve True se tratou como link; False = não era URL pura."""
        from okami.gateway import link_understanding as lu
        if not lu.is_pure_url(text):
            return False
        url = lu.detect_urls(text)[0]
        try:
            summary = lu.summarize_link(self.cfg, url)
        except Exception as e:  # noqa: BLE001 — best-effort: nunca derruba o poll por causa de um link
            summary = f"(não consegui abrir o link: {e})"
        self.channel.send(chat_id, "🔗 " + redact(summary))   # redige antes do send (#7 item 2)
        return True

    def apply_config(self, cfg) -> list[str]:
        """Re-aplica em quente SÓ os campos seguros da nova config (#12). Devolve o que mudou."""
        changed = []
        new_mode = (getattr(cfg, "approvals", None) or {}).get("mode", self.approval_mode)
        if new_mode != self.approval_mode:
            self.approval_mode = new_mode
            changed.append(_tr("gw.reload_approval", _default="approval={mode}", mode=new_mode))
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
        return True, (", ".join(changed) if changed else _tr(
            "gw.reload_no_changes", _default="no hot-applicable changes"))

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
                self.channel.send(chat, "👁 " + _tr(
                    "gw.notify_watch",
                    _default="process {id}: pattern «{pattern}» appeared ({count}×): {cmd}",
                    id=n["id"], pattern=n["pattern"], count=n["count"], cmd=str(n.get("cmd", ""))[:50]))
            else:
                self.channel.send(chat, "✅ " + _tr(
                    "gw.notify_done",
                    _default="process {id} finished (exit={exit_code}): {cmd}",
                    id=n["id"], exit_code=n.get("exit_code"), cmd=str(n.get("cmd", ""))[:60]))

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
                if not self._breaker.should_poll(self.surface):   # item 23: canal em backoff/pausa → pula
                    time.sleep(1)
                    continue
                self.poll_once()
                self._breaker.record_success(self.surface)        # poll ok → zera o backoff
                pace = getattr(self.channel, "poll_interval", 0)   # Telegram long-polla (0); REST espera
                if pace:
                    time.sleep(pace)
            except Exception:  # noqa: BLE001 — rede instável não derruba o bot
                secs = self._breaker.record_failure(self.surface)  # falha → backoff exponencial (não martela)
                time.sleep(min(secs, 3))
