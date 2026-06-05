"""EndpointCommandsMixin — handlers de slash command do AgentEndpoint (texto/estado, read-mostly).

Separado do endpoint.py p/ enxugar a classe: /help /commands /usage /tools /config /models /model
/sessions /resume /export /compact. Métodos ligam em `self` do AgentEndpoint (cfg/store/session/_run).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                                    # só p/ type-check/lint (sem circular em runtime)
    from okami.gateway.endpoint import Session


class EndpointCommandsMixin:
    """Slash commands do AgentEndpoint (mixin — os métodos resolvem self do AgentEndpoint)."""

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
