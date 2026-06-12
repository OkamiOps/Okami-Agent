"""Conversa multi-agente em grupo (§10/§13) — turn-taking estilo reunião de empresa.

Problema (mal resolvido no Hermes/OpenClaw): N agentes num grupo → ou spammam (LLM stampede)
ou só falam com @menção. Solução (papers "Speak or Stay Silent" / AutoGen SelectorGroupChat):
DISPATCH com eligibility gating + MODERADOR que escolhe quem fala (ou NINGUÉM) + cooldown +
silêncio intencional (agente pode dar PASS) + cap bot-to-bot (anti-loop).

O `GroupRoom` é o cérebro (channel-agnóstico). `select_speaker` e `respond` são injetados →
testável sem LLM; em produção, vêm dos factories abaixo (moderador barato + persona do agente).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_PASS = {"PASS", "SILENCE", "SILÊNCIO", "(SILÊNCIO)", "(PASS)", "—", "-"}
_STOP = {"STOP", "ENCERRAR", "ENCERRADO", "[STOP]", "FIM", "(STOP)"}
_STOP_RE = re.compile(r"\s*[\[(]?\bstop\b[\])]?[.!]*\s*$", re.IGNORECASE)   # "...decidido. STOP" → tira o token


@dataclass
class Member:
    id: str
    role: str = ""
    cooldown_until: int = 0     # turno a partir do qual volta a ser elegível


@dataclass
class GroupRoom:
    members: list[Member]
    select_speaker: Callable     # (history, candidates, mentioned) -> id | None
    respond: Callable            # (member, history) -> str ("" / "PASS" / "STOP")
    cooldown: int = 2            # turnos de silêncio após falar (a não ser @mencionado)
    max_bot_streak: int = 4      # mensagens de agente seguidas sem humano → para
    lead: str | None = None      # papel com AUTORIDADE de encerrar a discussão (ex.: 'cto')
    turn: int = 0
    bot_streak: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)

    def _member(self, mid: str) -> Member:
        return next(m for m in self.members if m.id == mid)

    def _eligible(self, mentioned: set[str], spoke: set[str]) -> list[Member]:
        if mentioned:                                   # @menção FORÇA (ignora cooldown, mas não re-fala)
            return [m for m in self.members if m.id in mentioned and m.id not in spoke]
        # 1 fala por agente por burst (deu opinião → espera/escuta) + cooldown entre bursts
        return [m for m in self.members if m.cooldown_until <= self.turn and m.id not in spoke]

    def dispatch(self, speaker_id: str, text: str, mentioned: set[str] | None = None) -> list[tuple[str, str]]:
        """Recebe uma mensagem; devolve as respostas (agente, texto) que devem ser enviadas."""
        self.turn += 1
        self.history.append((speaker_id, text))
        if speaker_id == "USER":
            self.bot_streak = 0
        replies: list[tuple[str, str]] = []
        cur_mentioned = set(mentioned or set())
        declined: set[str] = set()                       # deu PASS nesta troca (não mata a rodada)
        spoke: set[str] = set()                          # já falou neste burst (1 opinião/burst → escuta)
        while self.bot_streak < self.max_bot_streak:
            candidates = [c for c in self._eligible(cur_mentioned, spoke) if c.id not in declined]
            if not candidates:
                break
            sel = self.select_speaker(self.history, candidates, cur_mentioned)
            if not sel or sel not in {c.id for c in candidates}:
                break                                    # NINGUÉM / inelegível → silêncio do grupo
            m = self._member(sel)
            self.turn += 1
            reply = (self.respond(m, self.history) or "").strip()
            m.cooldown_until = self.turn + self.cooldown
            if not reply or reply.upper() in _PASS:      # CALAR → dá a vez ao próximo (não re-fala)
                declined.add(sel)
                spoke.add(sel)
                continue
            # STOP = encerrar a discussão. Autoridade do LEAD (ex.: CTO); de outro agente = só ele para.
            up = reply.upper()
            stop = up in _STOP or bool(_STOP_RE.search(reply))
            content = _STOP_RE.sub("", reply).strip() if stop else reply
            is_lead_stop = stop and (self.lead is None or sel == self.lead)
            if content:
                self.history.append((sel, content))
                replies.append((sel, content))
                self.bot_streak += 1
                cur_mentioned = set()                    # após o 1º round, @ não força mais
            spoke.add(sel)
            if is_lead_stop:
                break                                    # CTO encerrou → todos param
            if stop:                                     # 'stop' de não-lead = ele se cala (vira PASS)
                declined.add(sel)
        return replies


# --------------------------------------------------------------------- factories (produção)
def parse_mentions(text: str, member_ids: set[str]) -> set[str]:
    found = {m.lstrip("@").lower() for m in re.findall(r"@[\w-]+", text)}
    return {mid for mid in member_ids if mid.lower() in found}


def llm_moderator(cfg, provider: str | None = None) -> Callable:
    """Moderador: escolhe o próximo a falar ou 'none'. Usa constrained output (enum) → confiável
    mesmo em modelo fraco."""
    import json

    from okami.llm import providers as prov

    def select(history, candidates, mentioned):
        if mentioned:                                    # forçado → o(s) mencionado(s)
            return candidates[0].id
        convo = "\n".join(f"{s}: {t}" for s, t in history[-12:])
        roster = "\n".join(f"- {m.id}: {m.role}" for m in candidates)
        sysmsg = ("Você é o MODERADOR de um grupo de trabalho. Escolha QUEM deve falar a seguir, ou 'none'.\n"
                  "- Se o usuário dirige a fala a alguém (pelo nome/papel) ou pergunta algo do domínio de um "
                  "agente, escolha esse agente.\n"
                  "- A ÚLTIMA fala pode ser de OUTRO AGENTE: se ele disse algo ERRADO ou discutível no "
                  "domínio de um colega, escolha esse colega para CORRIGIR/comentar (uma vez).\n"
                  "- Se o líder já decidiu/encerrou, ou ninguém tem nada essencial a dizer agora, responda "
                  "'none'. Prefira 'none' a forçar conversa. Não escolha quem já falou agora.")
        idlist = ", ".join(m.id for m in candidates)
        msgs = [{"role": "system", "content": sysmsg},
                {"role": "user", "content": f"AGENTES (id: papel):\n{roster}\n\nCONVERSA:\n{convo}\n\n"
                                             f"Responda APENAS com um id ({idlist}) ou 'none'. Quem fala?"}]
        ids = {m.id.lower(): m.id for m in candidates}
        schema = {"type": "object",
                  "properties": {"speaker": {"type": "string", "enum": [m.id for m in candidates] + ["none"]}},
                  "required": ["speaker"]}
        # moderar é trabalho de FUNDO → modelo auxiliar barato (pesquisa #5 item 57); provider
        # explícito do chamador vence a config auxiliar.
        from okami.llm.aux import aux_for
        aux_p, aux_m = (provider, None) if provider else aux_for(cfg, "moderator")
        out = prov.complete_messages(cfg, msgs, provider=aux_p, model=aux_m,
                                     response_schema=schema).strip()
        try:
            speaker = str(json.loads(out).get("speaker", "")).lower()
        except (json.JSONDecodeError, AttributeError):
            speaker = out.lower()
        if speaker in ids:
            return ids[speaker]
        for tok in re.split(r"[\s,.;:{}\"']+", speaker):   # fallback: varre tokens
            if tok in ids:
                return ids[tok]
        return None
    return select


def agent_responder(global_raw: dict, agents: dict, max_chars: int = 600,
                    lead: str | None = None) -> Callable:
    """Cada agente responde NO SEU PRÓPRIO MODELO; 'PASS' = silêncio, 'STOP' = encerrar (só o lead).

    Pontos críticos (§10): (1) o modelo é o do AGENTE — `effective_config` mescla o `agent.yaml`
    (que define `default_provider`) sobre o global, então cada agente roda o SEU provider/modelo
    enquanto as CREDENCIAIS (`providers:`) ficam globais; (2) execução ISOLADA — uma chamada
    single-shot por agente, sem Harness/sessão/janela compartilhada (conversa de grupo é FALA,
    não tarefa; single-shot é confiável até em modelo fraco). Trabalho de fato = `okami task -a`.
    Cada agente OUVE as falas dos colegas (estão no histórico) e pode CORRIGIR no seu domínio.
    """
    from okami.llm import providers as prov
    from okami.agents import effective_config
    from okami.memory import files as memfiles

    def respond(member: Member, history):
        spec = agents[member.id]
        cfg = effective_config(global_raw, spec)             # ← provider/modelo PRÓPRIOS do agente
        identity = memfiles.core_block(spec.dir, cfg.memory.get("files", {}))   # SOUL/VOICE/PERSONA/...
        convo = "\n".join(f"{s}: {t}" for s, t in history[-12:])
        role = member.role or "membro da equipe"
        rules = ("Você está num GRUPO de trabalho da empresa (chat) com o usuário e outros agentes. "
                 "Responda à ÚLTIMA fala NO SEU PAPEL, curto e humano (1-2 frases), sem repetir o que já "
                 "foi dito.\n"
                 "- A última fala pode ser de um COLEGA: se ele errou algo no SEU domínio, CORRIJA com "
                 "fundamento (uma vez). Se concorda ou não é seu domínio, não comente.\n"
                 "- Se você JÁ deu sua opinião e o ponto foi endereçado, ou não tem nada material a "
                 "acrescentar, responda EXATAMENTE 'PASS' (fica só escutando).")
        if lead and member.id == lead:
            rules += ("\n- Você é o LÍDER: quando a decisão estiver tomada e a discussão resolvida, "
                      "encerre respondendo 'STOP' (ou 'sua conclusão. STOP') — aí todos param.")
        sysmsg = (identity + "\n\n" if identity else "") + f"SEU PAPEL no grupo: {role}.\n" + rules
        msgs = [{"role": "system", "content": sysmsg},
                {"role": "user", "content": f"CONVERSA:\n{convo}\n\nSua resposta (ou 'PASS'):"}]
        out = (prov.complete_messages(cfg, msgs) or "").strip()   # provider=None → cfg.default_provider do agente
        return out[:max_chars]
    return respond


def build_room(global_raw: dict, agents: dict, group_cfg: dict, moderator_cfg=None,
               select_speaker=None, respond=None) -> GroupRoom:
    member_ids = [mid for mid in group_cfg.get("members", []) if mid in agents]
    members = [Member(mid, role=agents[mid].raw.get("role", "")) for mid in member_ids]
    # lead = quem encerra a discussão (explícito no group_cfg, ou o 1º membro = ex.: CTO)
    lead = group_cfg.get("lead") or (member_ids[0] if member_ids else None)
    sel = select_speaker or llm_moderator(moderator_cfg) if moderator_cfg is not None else select_speaker
    rsp = respond or agent_responder(global_raw, agents, lead=lead)
    return GroupRoom(members=members, select_speaker=sel, respond=rsp, lead=lead,
                     cooldown=int(group_cfg.get("cooldown", 2)),
                     max_bot_streak=int(group_cfg.get("max_bot_streak", 4)))
