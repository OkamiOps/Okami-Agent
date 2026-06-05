"""Gateway de mensageria (§13) — control plane channel-agnóstico (estilo OpenClaw).

Por agente: um Channel (Telegram/…) → Sessões por chat (continuidade de conversa) → roda a tarefa
no workspace do agente. Robustez: histórico por sessão, slash commands (/new /reset /status /stop
/yolo /help), concorrência (uma tarefa por sessão), go/no-go por chat (timeout fail-closed), `/stop`
que CANCELA de verdade (callback no harness).
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable

from okami.gateway.sessions import TranscriptStore


# ----------------------------------------------------------------- gênese / primeiro contato (§8.2)
# OpenClaw-style: na PRIMEIRA conversa o agente "recém-nascido" conduz um onboarding curto — conhece
# a pessoa e deixa ELA moldar SOUL/VOICE/PERSONA. Some assim que selado (.okami/genesis.done).
GENESIS_BLOCK = """=== PRIMEIRO CONTATO · GÊNESE (uso interno — NÃO cite isto; só AJA assim) ===
Esta é a sua PRIMEIRA conversa com esta pessoa e você acabou de nascer: ainda não te configuraram.
Não importa o que ela mandou (até um "oi"): conduza um primeiro papo curto e caloroso pra (1) conhecer
ELA e (2) deixar ELA moldar quem VOCÊ é.
- Cumprimente de leve e diga em UMA frase que você tá começando agora e quer se acertar com ela.
- Puxe conversa de leve, UMA coisa de cada vez (nada de formulário): como ela quer te chamar; no que
  ela trabalha / o que vocês vão tocar juntos; e que JEITO ela quer que você tenha (mais solto ou formal?
  direto ou explicador? pode brincar/xingar ou nem tanto?).
- Conforme ela responde, ESCREVA a identidade no tom dela com write_file, curtinha (3 blocos cada):
  SOUL.md (valores/essência) · VOICE.md (tom/estilo) · PERSONA.md (jeito/expertise). Mostra o que
  escreveu e pergunta se ficou com a cara dela.
- Quando ela estiver satisfeita, chame `finish_setup` (em `about_user`, 1 linha sobre quem ela é) —
  isso ENCERRA a configuração. Se ela quiser deixar pra depois, chame finish_setup mesmo assim (sem
  about_user) pra você não ficar perguntando toda hora.
Não use remember_user agora — o about_user do finish_setup já cuida disso.
==="""


def genesis_pending(ws) -> bool:
    """Gênese pendente? (primeira config ainda não feita). Selado por .okami/genesis.done; um agente
    pré-existente que JÁ conhece o usuário (tem USER.md) é considerado configurado e é selado na hora."""
    ws = Path(ws)
    if (ws / ".okami" / "genesis.done").exists():
        return False
    if (ws / "USER.md").exists():            # já conhece a pessoa → não re-onboarda; sela uma vez
        _seal_genesis(ws)
        return False
    return True


def _seal_genesis(ws) -> None:
    marker = Path(ws) / ".okami" / "genesis.done"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("done\n", encoding="utf-8")


def _history_block(history: list[tuple[str, str]], limit: int = 6, max_chars: int = 6000) -> str:
    """Histórico recente capado por nº de trocas E por chars (proporcional à janela do modelo)."""
    if not history:
        return ""
    lines, total = [], 0
    for role, text in reversed(history[-limit * 2:]):
        line = f"{role}: {text}"
        if total + len(line) > max_chars and lines:
            break
        lines.append(line)
        total += len(line)
    lines.reverse()
    return "CONVERSA RECENTE (continue o contexto, não repita o que já foi dito):\n" + "\n".join(lines)


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

    def interrupted(self) -> bool:
        """Tarefa interrompida = histórico termina numa fala do USER sem resposta do AGENTE."""
        return bool(self.history) and self.history[-1][0] == "USER"


class AgentEndpoint:
    """Liga um agente ao seu canal; gerencia sessões por chat."""

    def __init__(self, agent_id: str, cfg, ws, channel, run_task: Callable,
                 approval_mode: str = "manual", approval_timeout: float = 120.0,
                 max_history_chars: int = 6000, stt=None, tts=None, spawn: Callable | None = None,
                 auto_resume: bool = False, max_sessions: int = 500, on_event: Callable | None = None):
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
        self.sessions: dict[str, Session] = {}
        self._pending: dict[str, queue.Queue] = {}
        self._img: dict[str, str] = {}       # imagem pendente por chat (vision §6)
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
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
                                resume_attempts=s.resume_attempts, reasoning_effort=s.reasoning_effort)

    def _all_session_ids(self) -> list[str]:
        return self.store.ids()

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

    def _help(self) -> str:
        from okami import commands as _cmds
        ess = ", ".join("/" + c.name for cs in _cmds.by_category(tier="essential").values() for c in cs)
        return (f"Sou o agente '{self.agent_id}'. Manda a tarefa.\n"
                f"Essenciais: {ess}\n/commands lista TODOS por categoria.")

    def _commands_text(self) -> str:
        from okami import commands as _cmds
        return "📜 comandos por categoria:\n" + "\n".join(_cmds.help_lines())

    def _usage_text(self, chat_id) -> str:
        from okami.llm.usage import CanonicalUsage, estimate_cost, format_tokens
        e = (self.store.entry(chat_id) if self.store else {}) or {}
        u = CanonicalUsage.from_dict(e.get("usage") or {})
        if not u.total_tokens:
            return "📊 ainda sem tokens contabilizados nesta sessão."
        line = f"📊 {format_tokens(u.input_tokens)} in · {format_tokens(u.output_tokens)} out"
        if u.cache_read_tokens:
            line += f" · {format_tokens(u.cache_read_tokens)} cache"
        pc = self.cfg.provider() if self.cfg else None
        if pc:
            cr = estimate_cost(u, transport=pc.transport, provider=self.cfg.default_provider, model=pc.model)
            line += f"   custo {cr.label}"
        if e.get("served_by"):
            line += f"\nservido por: {e['served_by']}"
        return line

    def _tools_text(self) -> str:
        from okami.core.tool_registry import by_category
        from okami.core.tools import default_registry
        names = {n for n in default_registry() if not n.startswith("task_") and n != "need_input"}
        lines = ["🧰 ferramentas:"]
        for cat, specs in by_category(names).items():
            lines.append(f"• {cat}: " + ", ".join(s.name for s in specs))
        return "\n".join(lines)

    def _config_text(self) -> str:
        import yaml as _yaml
        try:
            from okami.cli import _redact
            from okami.config import load_raw
            raw, _ = load_raw()
            dump = _yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False)
            return "⚙ config efetiva (segredos mascarados):\n" + dump[:1500]
        except Exception as e:  # noqa: BLE001
            return f"❌ não consegui ler a config: {e}"

    def _models_text(self) -> str:
        if not self.cfg:
            return "—"
        pc = self.cfg.provider()
        models = getattr(pc, "models", None) or [pc.model]
        return (f"🧠 modelos de {self.cfg.default_provider}: " + ", ".join(models)
                + "\nproviders: " + ", ".join(self.cfg.providers))

    def _model_cmd(self, s: "Session", arg: str) -> str:
        pc = self.cfg.provider() if self.cfg else None
        if not arg:
            cur = s.model_override or (pc.model if pc else "?")
            return f"🧠 modelo: {cur}" + (" (override desta sessão)" if s.model_override else "") + " · /models lista"
        s.model_override = arg
        return f"🧠 modelo desta sessão → {arg} (vale nos próximos turnos; /model sem arg mostra)"

    def _sessions_text(self, chat_id) -> str:
        import datetime as _dt
        arr = self.store.archives(chat_id)
        if not arr:
            return "🗂 nenhuma conversa arquivada (o /new arquiva a atual)."
        out = ["🗂 conversas arquivadas — /resume <n>:"]
        for i, a in enumerate(arr[:15], 1):
            when = _dt.datetime.fromtimestamp(a["ts"]).strftime("%d/%m %H:%M") if a["ts"] else "?"
            out.append(f"  {i}. {when} · {a['turns']} trocas")
        return "\n".join(out)

    def _resume_cmd(self, chat_id, s: "Session", arg: str) -> str:
        arr = self.store.archives(chat_id)
        if not arr:
            return "nada pra retomar (veja /sessions)."
        try:
            name = arr[int(arg) - 1]["name"]
        except (ValueError, IndexError):
            return "uso: /resume <n> (o número vem do /sessions)."
        try:
            hist = self.store.resume(chat_id, name)
        except Exception as e:  # noqa: BLE001
            return f"❌ não retomei: {e}"
        s.history[:] = list(hist)
        return f"↻ retomei a conversa ({len(hist) // 2} trocas). Pode continuar de onde parou."

    def _export_cmd(self, chat_id, arg: str) -> str:
        import time as _t
        from pathlib import Path as _P
        name = arg or f"conversa_{chat_id}_{int(_t.time())}.md"
        dest = _P(name) if _P(name).is_absolute() else _P(self.ws) / name
        try:
            out = self.store.export(chat_id, dest)
            return f"📄 exportado em Markdown: {out}"
        except Exception as e:  # noqa: BLE001
            return f"❌ export falhou: {e}"

    def _compact_now(self, chat_id, s: "Session") -> str:
        if len(s.history) < 4:
            return "🗜 nada relevante pra compactar ainda."
        from okami.llm import providers as prov
        try:
            convo = "\n".join(f"{r}: {t}" for r, t in s.history[-40:])
            summary = prov.complete_messages(self.cfg, [
                {"role": "system", "content": "Resuma em 1 parágrafo, preservando decisões, fatos e pendências."},
                {"role": "user", "content": convo}]).strip()
            if not summary:
                return "🗜 sem resumo (modelo vazio)."
            node = "[resumo da conversa] " + summary[:1500]
            self.store.compact(chat_id, node)
            s.history[:] = [("SUMMARY", node), *s.history[-4:]]
            return "🗜 contexto compactado (mantive as últimas trocas)."
        except Exception as e:  # noqa: BLE001
            return f"❌ compact falhou: {e}"

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
            nonce = secrets.token_hex(4)                 # amarra o botão a ESTE pedido (P1.3 anti-stale)
            q: queue.Queue = queue.Queue()
            self._pending[str(chat_id)] = (q, nonce)
            _sa = getattr(self.channel, "send_approval", None)   # botões inline se o canal suportar
            if _sa:
                try:
                    _sa(chat_id, f"⚠ Aprovar: {req['reason']}?", nonce=nonce)
                except TypeError:                        # canal sem suporte a nonce → compat
                    _sa(chat_id, f"⚠ Aprovar: {req['reason']}?")
            else:
                self.channel.send(chat_id, f"⚠ Aprovar: {req['reason']}? (/yes ou /no)")
            try:
                ans = q.get(timeout=self.approval_timeout)
            except queue.Empty:
                ans = "/no"
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
        text = (text or "").strip()
        cid = str(chat_id)
        if cid in self._pending:                       # resposta a uma aprovação pendente
            pend = self._pending[cid]
            q, want = pend if isinstance(pend, tuple) else (pend, "")   # tolera fila pura (compat)
            verb, _, got = text.partition(":")         # "/yes" | "/yes:<nonce>" (botão)
            if got and want and got != want:           # nonce velho/errado = clique stale → IGNORA
                self.channel.send(chat_id, "⌛ esse botão expirou (outra ação aconteceu). Use /yes ou /no.")
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
            self.channel.send(chat_id, f"agente {self.agent_id} · "
                              f"{'ocupado' if s.busy else 'livre'} · {len(s.history) // 2} trocas · "
                              f"yolo={'on' if s.yolo else 'off'}")
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
        from okami.automation.scheduler import Scheduler, infer_commitment   # §11: "me lembra de X amanhã" → agenda
        ic = infer_commitment(text, time.time())
        if ic:
            schedule, prompt = ic
            job = Scheduler(".").add(schedule, prompt, agent=self.agent_id, target=str(chat_id))
            self.channel.send(chat_id, f"⏰ agendei [{job['schedule']}]: {prompt}")
            return
        if s.busy:
            self.channel.send(chat_id, "⏳ ainda processando a anterior. Use /stop para cancelar.")
            return
        s.busy = True
        s.cancel = False
        self._spawn(lambda: self._run(chat_id, text, s, images=self._img.pop(cid, None)))

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
        self.channel.send(chat_id, f"💭 {self.agent_id} está pensando…")
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
            task = self.run_task(self.cfg, self.ws, text, **kw)
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
            self._maybe_voice(chat_id, reply)
            self._observe(chat_id, text)                  # aprende o estilo do usuário (gradual, auto)
            self._observe_llm(chat_id, s)                 # a cada N turnos, leitura mais rica por LLM
            self._maybe_compact(chat_id)                  # transcript longo → nó SUMMARY (§6.4)
        except Exception as e:  # noqa: BLE001 — USER já está no transcript → detectável como interrompido
            self.channel.send(chat_id, f"❌ erro: {e}")
        finally:
            s.busy = False
            s.cancel = False

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

    def loop(self) -> None:
        while self.running:
            try:
                self.poll_once()
                pace = getattr(self.channel, "poll_interval", 0)   # Telegram long-polla (0); REST espera
                if pace:
                    time.sleep(pace)
            except Exception:  # noqa: BLE001 — rede instável não derruba o bot
                time.sleep(3)


class GroupEndpoint:
    """Um GRUPO multi-agente sobre um canal (§10/§13): escuta o chat, roda o `GroupRoom` em cada
    mensagem HUMANA e cada agente responde PELA SUA PRÓPRIA token. O anti-stampede vem do GroupRoom
    (moderador decide quem fala/ninguém + cooldown + caps). Síncrono e ordenado: um burst por vez —
    mensagens que chegam durante um burst esperam no canal e entram no próximo poll."""

    def __init__(self, room, channel, *, label: str = "group", min_delay: float = 0.0,
                 store_root: str = ".", emit: Callable[[str], None] = lambda m: None):
        self.room = room              # GroupRoom (membros + moderador + responder)
        self.channel = channel        # poll() / send_as(agent_id, chat_id, text) / allowed()
        self.label = label
        self.min_delay = min_delay     # pausa entre falas (parece humano; 0 nos testes)
        self.emit = emit
        self.running = True
        self._started = False
        self.store = TranscriptStore(store_root, subdir="groups")   # transcript do grupo (2 camadas §13)
        self._hydrate()               # restart: recarrega a conversa e os cooldowns do disco

    def _hydrate(self) -> None:
        """Restart: rebuild da conversa do grupo + estado de turn-taking (turn/cooldowns)."""
        self.room.history = self.store.history(self.label, limit=40)
        e = self.store.entry(self.label)
        self.room.turn = int(e.get("turn", 0))
        self.room.bot_streak = 0      # humano sempre zera; não faz sentido persistir streak
        cds = e.get("cooldowns") or {}
        for m in self.room.members:
            m.cooldown_until = int(cds.get(m.id, 0))

    def _save_state(self) -> None:
        self.store.update_entry(self.label, turn=self.room.turn,
                                cooldowns={m.id: m.cooldown_until for m in self.room.members})

    def handle(self, chat_id, text: str, mentioned=None) -> list[tuple[str, str]]:
        if not self.channel.allowed(chat_id):
            return []
        self.store.append(self.label, "USER", text)    # transcript append-only (sobrevive a restart)
        replies = self.room.dispatch("USER", text, mentioned=mentioned)
        for agent_id, reply in replies:
            self.channel.send_as(agent_id, chat_id, reply)
            self.store.append(self.label, agent_id, reply)   # cada fala de agente vira um nó (papel=id)
            if self.min_delay:
                time.sleep(self.min_delay)
        if not replies:
            self.emit(f"[{self.label}] ninguém se manifestou (sem stampede)")
        self._save_state()
        return replies

    def poll_once(self) -> None:
        from okami.agents.group import parse_mentions
        for msg in self.channel.poll():                 # canal já filtra mensagens dos próprios bots
            if not msg.text:
                continue
            mentioned = parse_mentions(msg.text, {m.id for m in self.room.members})
            self.handle(msg.chat_id, msg.text, mentioned=mentioned)

    def loop(self) -> None:
        if not self._started:
            try:
                self.channel.start()
            except Exception:  # noqa: BLE001
                pass
            self._started = True
        while self.running:
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 — rede instável não derruba o grupo
                time.sleep(3)


def build_group_endpoints(global_raw: dict, agents: dict, groups: list,
                          emit: Callable[[str], None] = lambda m: None,
                          make_channel=None) -> list["GroupEndpoint"]:
    """Um GroupEndpoint por grupo em okami.yaml (groups). Cada membro entra com a SUA token
    (channels.telegram.token do agent.yaml); o grupo precisa de ≥1 membro com token."""
    from okami.channels.telegram import TelegramGroupChannel
    from okami.config import build_config
    from okami.agents.group import agent_responder, build_room, llm_moderator

    eps: list[GroupEndpoint] = []
    for gi, gcfg in enumerate(groups or []):
        member_ids = [m for m in (gcfg.get("members") or []) if m in agents]
        tokens = {aid: ((agents[aid].raw.get("channels") or {}).get("telegram") or {}).get("token")
                  for aid in member_ids}
        tokens = {aid: t for aid, t in tokens.items() if t}
        if not tokens:
            emit(f"grupo {gi}: nenhum membro com channels.telegram.token — pulando")
            continue
        mod_provider = (gcfg.get("moderator") or {}).get("provider")
        room = build_room(global_raw, agents, gcfg,
                          select_speaker=llm_moderator(build_config(global_raw), provider=mod_provider),
                          respond=agent_responder(global_raw, agents))
        g_allow, g_all = gcfg.get("allow_chats"), bool(gcfg.get("allow_all", False))
        if not g_allow and not g_all:
            emit(f"⚠ [grupo{gi}] sem allowlist → deny-by-default. Configure allow_chats ou allow_all: true.")
        channel = (make_channel or TelegramGroupChannel)(tokens, allow_chats=g_allow, allow_all=g_all)
        eps.append(GroupEndpoint(room, channel, label=f"grupo{gi}",
                                 min_delay=float(gcfg.get("min_delay", 0.0)), emit=emit))
        emit(f"grupo {gi} no ar: {', '.join(tokens)} ({len(tokens)} bots) · moderador={mod_provider or 'default'}")
    return eps


def _build_channel(ctype: str, cc: dict):
    """Fábrica de canal não-Telegram (#15). KeyError se faltar um campo obrigatório."""
    common = {"allow_chats": cc.get("allow_chats"), "allow_all": bool(cc.get("allow_all", False))}
    if ctype == "slack":
        from okami.channels.slack import SlackChannel
        return SlackChannel(cc["token"], cc["channel_id"], **common)
    if ctype == "discord":
        from okami.channels.discord import DiscordChannel
        return DiscordChannel(cc["token"], cc["channel_id"], **common)
    if ctype == "mattermost":
        from okami.channels.mattermost import MattermostChannel
        return MattermostChannel(cc["base_url"], cc["token"], cc["channel_id"], **common)
    raise KeyError(ctype)


def build_endpoints(global_raw: dict, agents: dict, emit: Callable[[str], None] = lambda m: None,
                    make_channel=None, run_task=None) -> list[AgentEndpoint]:
    from okami.agents import effective_config
    from okami.channels.telegram import TelegramChannel
    from okami.runner import run_task as _default_run_task

    run_task = run_task or _default_run_task

    def _mk_endpoint(aid, spec, cfg, channel) -> AgentEndpoint:
        # histórico da sessão ~12% da janela do modelo (32K Qwen guarda menos; 200K Claude mais).
        from okami.llm.providers import context_window_tokens
        from okami.voice import make_stt, make_tts
        pc = cfg.provider()
        hist_chars = max(2000, int(context_window_tokens(pc) * pc.chars_per_token * 0.12))
        voice = cfg.voice or {}
        gw = cfg.gateway or {}
        return AgentEndpoint(aid, cfg, spec.dir, channel, run_task=run_task,
                             approval_mode=(cfg.approvals or {}).get("mode", "manual"),
                             max_history_chars=hist_chars,
                             stt=make_stt(voice.get("stt")), tts=make_tts(voice.get("tts")),
                             auto_resume=bool(gw.get("auto_resume", False)),
                             max_sessions=int(gw.get("max_sessions", 500)))

    eps: list[AgentEndpoint] = []
    for aid, spec in agents.items():
        chans = spec.raw.get("channels") or {}
        cfg = None
        tg = chans.get("telegram") or {}
        if tg.get("token"):                            # Telegram (mantém make_channel p/ os testes)
            cfg = effective_config(global_raw, spec)
            if not tg.get("allow_chats") and not tg.get("allow_all"):   # fail-closed: avisa ALTO
                emit(f"⚠ [{aid}] Telegram SEM allowlist → deny-by-default (bot não responde ninguém). "
                     f"Adicione channels.telegram.allow_chats: [<seu_chat_id>] ou allow_all: true (inseguro).")
            channel = (make_channel or TelegramChannel)(tg["token"], allow_chats=tg.get("allow_chats"),
                                                        allow_all=bool(tg.get("allow_all", False)))
            eps.append(_mk_endpoint(aid, spec, cfg, channel))
            emit(f"agente '{aid}' no ar (canal {channel.name})")
        for ctype in ("slack", "discord", "mattermost"):     # #15: mais canais, mesma interface
            cc = chans.get(ctype) or {}
            if not cc.get("token"):
                continue
            try:
                channel = _build_channel(ctype, cc)
            except KeyError as e:
                emit(f"⚠ [{aid}] {ctype}: faltando campo {e} — pulei esse canal.")
                continue
            if not cc.get("allow_chats") and not cc.get("allow_all"):
                emit(f"⚠ [{aid}] {ctype} sem allowlist → só o canal configurado responde (deny-by-default).")
            cfg = cfg or effective_config(global_raw, spec)
            eps.append(_mk_endpoint(aid, spec, cfg, channel))
            emit(f"agente '{aid}' no ar (canal {channel.name})")
    return eps


def _start_scheduler(eps: list, emit: Callable[[str], None], interval: float = 30.0) -> None:
    """Sobe o scheduler (§11): a cada `interval`s roda jobs vencidos e ENTREGA o resultado no chat."""
    from okami.automation.scheduler import Scheduler

    sched = Scheduler(".")
    if not sched.load():
        return
    by_agent = {ep.agent_id: ep for ep in eps}

    def execute(job):
        ep = by_agent.get(job.get("agent")) or (eps[0] if eps else None)
        if ep is None:
            return "(sem endpoint p/ entregar)"
        task = ep.run_task(ep.cfg, ep.ws, job["prompt"])
        result = task.result or task.reason or task.state.value
        if job.get("target"):                          # entrega no chat (estilo OpenClaw cron→canal)
            ep.channel.send(job["target"], f"⏰ {job['id']}: {result}")
        return result

    def loop():
        while True:
            try:
                sched.tick(execute)
            except Exception:  # noqa: BLE001 — scheduler nunca derruba o gateway
                pass
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    emit(f"⏰ scheduler no ar ({len(sched.load())} job(s)).")


def run_gateway(global_raw: dict, agents: dict, emit: Callable[[str], None] = print, make_channel=None):
    from okami.config import build_config

    eps = build_endpoints(global_raw, agents, emit=emit, make_channel=make_channel)   # DMs (1 agente/chat)
    groups = build_group_endpoints(global_raw, agents, build_config(global_raw).groups, emit=emit)  # salas
    everyone = [*eps, *groups]
    if not everyone:
        emit("nada a rodar (nenhum agente com channels.telegram.token, nem grupo).")
        return everyone
    for ep in eps:                                     # boot: limpa sessões velhas + retoma interrompidas
        try:
            n = ep.prune_sessions(max_sessions=ep.max_sessions)
            if n:
                emit(f"agente '{ep.agent_id}': {n} sessão(ões) antiga(s) podada(s)")
            ep.resume_interrupted(auto_resume=ep.auto_resume)
        except Exception:  # noqa: BLE001
            pass
    for ep in everyone:
        threading.Thread(target=ep.loop, daemon=True).start()
    _start_scheduler(eps, emit)                        # §11: jobs agendados entregam no chat
    emit(f"gateway no ar: {len(eps)} agente(s) DM + {len(groups)} grupo(s). Ctrl+C para sair.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for ep in everyone:
            ep.running = False
    return everyone
