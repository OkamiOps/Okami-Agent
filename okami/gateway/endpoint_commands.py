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
        from okami.i18n import t
        ess = ", ".join("/" + c.name for cs in _cmds.by_category(tier="essential").values() for c in cs)
        return t("chat.help", agent=self.agent_id, ess=ess)

    def _commands_text(self) -> str:
        from okami import commands as _cmds
        from okami.i18n import t
        return t("chat.commands_header") + "\n" + "\n".join(_cmds.help_lines())

    def _usage_text(self, chat_id) -> str:
        from okami.i18n import t
        from okami.llm.usage import CanonicalUsage, estimate_cost, format_tokens
        e = (self.store.entry(chat_id) if self.store else {}) or {}
        u = CanonicalUsage.from_dict(e.get("usage") or {})
        if not u.total_tokens:
            return "📊 " + t("gw.usage_none", _default="no tokens counted in this session yet.")
        line = f"📊 {format_tokens(u.input_tokens)} in · {format_tokens(u.output_tokens)} out"
        if u.cache_read_tokens:
            line += f" · {format_tokens(u.cache_read_tokens)} cache"
        pc = self.cfg.provider() if self.cfg else None
        if pc:
            cr = estimate_cost(u, transport=pc.transport, provider=self.cfg.default_provider, model=pc.model)
            line += "   " + t("gw.usage_cost", _default="cost {label}", label=cr.label)
        if e.get("served_by"):
            line += "\n" + t("gw.usage_served_by", _default="served by: {by}", by=e["served_by"])
        return line

    def _tools_text(self) -> str:
        from okami.core.tool_registry import by_category
        from okami.core.tools import default_registry
        from okami.i18n import t
        names = {n for n in default_registry() if not n.startswith("task_") and n != "need_input"}
        lines = ["🧰 " + t("gw.tools_header", _default="tools:")]
        for cat, specs in by_category(names).items():
            lines.append(f"• {cat}: " + ", ".join(s.name for s in specs))
        return "\n".join(lines)

    def _config_text(self) -> str:
        import yaml as _yaml

        from okami.i18n import t
        try:
            from okami.cli import _redact
            from okami.config import load_raw
            raw, _ = load_raw()
            dump = _yaml.safe_dump(_redact(raw), allow_unicode=True, sort_keys=False)
            return "⚙ " + t("gw.config_header", _default="effective config (secrets masked):") + "\n" + dump[:1500]
        except Exception as e:  # noqa: BLE001
            return "❌ " + t("gw.config_read_fail", _default="couldn't read the config: {e}", e=e)

    def _models_text(self) -> str:
        from okami.i18n import t
        if not self.cfg:
            return "—"
        lines = ["🧠 " + t("gw.models_header", _default="providers (switch with /model <name>):")]
        for name, pc in self.cfg.providers.items():
            star = "★ " if name == self.cfg.default_provider else "  "
            if pc.experimental:
                state = t("gw.models_experimental", _default="experimental")
            elif pc.ready:
                state = "✓ " + t("gw.models_ready", _default="ready")
            else:
                state = "⚠ " + t("gw.models_missing", _default="missing: okami login {name}", name=name)
            lines.append(f"  {star}{name} · {pc.model} [{state}]")
        lines.append(t(
            "gw.models_tip",
            _default="tip: /model codex = OpenAI (GPT-5) via your ChatGPT subscription — no API key."))
        return "\n".join(lines)

    def _model_cmd(self, s: "Session", arg: str) -> str:
        from okami.i18n import t
        provs = self.cfg.providers if self.cfg else {}
        if not arg:
            prov = s.provider_override or (self.cfg.default_provider if self.cfg else "?")
            cur = s.model_override or (provs[prov].model if prov in provs else "?")
            tag = (" · " + t("gw.model_provider_tag", _default="provider {prov}", prov=prov)) if s.provider_override else ""
            ov = (" " + t("gw.model_session_override", _default="(this session's override)")) \
                if (s.model_override or s.provider_override) else ""
            return "🧠 " + t(
                "gw.model_current", _default="model: {cur}", cur=cur) + tag + ov + " · " + t(
                "gw.model_lists", _default="/models lists providers and models")
        # `/model codex` (ou `/model codex gpt-5.4`): arg começa com um PROVIDER configurado → TROCA de
        # provider (ex.: codex = OpenAI via assinatura, SEM API key). Senão, arg é só o modelo no provider atual.
        first, _, rest = arg.partition(" ")
        if first in provs:
            s.provider_override = first
            s.model_override = rest.strip()          # vazio → usa o modelo default daquele provider
            pc = provs[first]
            ready = "" if pc.ready else " ⚠ " + t(
                "gw.model_need_auth", _default="need to authenticate: okami login {first}", first=first)
            return "🧠 " + t(
                "gw.model_provider_set",
                _default="provider for this session → {first} ({model}).", first=first,
                model=s.model_override or pc.model) + ready + " " + t(
                "gw.model_next_turns_use", _default="Next turns use it.")
        s.model_override = arg
        return "🧠 " + t(
            "gw.model_set",
            _default="model for this session → {arg} (applies next turns; /model with no arg shows it)", arg=arg)

    def _sessions_text(self, chat_id) -> str:
        import datetime as _dt

        from okami.i18n import t
        arr = self.store.archives(chat_id)
        if not arr:
            return "🗂 " + t("gw.sessions_none", _default="no archived conversations (/new archives the current one).")
        out = ["🗂 " + t("gw.sessions_header", _default="archived conversations — /resume <n>:")]
        for i, a in enumerate(arr[:15], 1):
            when = _dt.datetime.fromtimestamp(a["ts"]).strftime("%d/%m %H:%M") if a["ts"] else "?"
            out.append("  " + t(
                "gw.sessions_row", _default="{i}. {when} · {turns} exchanges",
                i=i, when=when, turns=a["turns"]))
        return "\n".join(out)

    def _resume_cmd(self, chat_id, s: "Session", arg: str) -> str:
        from okami.i18n import t
        arr = self.store.archives(chat_id)
        if not arr:
            return t("gw.resume_nothing", _default="nothing to resume (see /sessions).")
        try:
            name = arr[int(arg) - 1]["name"]
        except (ValueError, IndexError):
            return t("gw.resume_usage", _default="usage: /resume <n> (the number comes from /sessions).")
        try:
            hist = self.store.resume(chat_id, name)
        except Exception as e:  # noqa: BLE001
            return "❌ " + t("gw.resume_fail", _default="couldn't resume: {e}", e=e)
        s.history[:] = list(hist)
        return "↻ " + t(
            "gw.resume_done",
            _default="resumed the conversation ({turns} exchanges). You can continue where you left off.",
            turns=len(hist) // 2)

    def _export_cmd(self, chat_id, arg: str) -> str:
        import time as _t
        from pathlib import Path as _P

        from okami.i18n import t
        name = arg or f"conversa_{chat_id}_{int(_t.time())}.md"
        dest = _P(name) if _P(name).is_absolute() else _P(self.ws) / name
        try:
            out = self.store.export(chat_id, dest)
            return "📄 " + t("gw.export_done", _default="exported to Markdown: {out}", out=out)
        except Exception as e:  # noqa: BLE001
            return "❌ " + t("gw.export_fail", _default="export failed: {e}", e=e)

    def _compact_now(self, chat_id, s: "Session") -> str:
        from okami.i18n import t as _i18n
        if len(s.history) < 4:
            return "🗜 " + _i18n("gw.compact_nothing", _default="nothing relevant to compact yet.")
        from okami.llm.aux import aux_complete   # compressão é FUNDO → modelo auxiliar barato (item 57)
        try:
            convo = "\n".join(f"{r}: {t}" for r, t in s.history[-40:])
            summary = aux_complete(self.cfg, "compress", [
                {"role": "system", "content": "Resuma em 1 parágrafo, preservando decisões, fatos e pendências."},
                {"role": "user", "content": convo}]).strip()
            if not summary:
                return "🗜 " + _i18n("gw.compact_no_summary", _default="no summary (empty model).")
            node = "[resumo da conversa] " + summary[:1500]
            self.store.compact(chat_id, node)
            s.history[:] = [("SUMMARY", node), *s.history[-4:]]
            return "🗜 " + _i18n("gw.compact_done", _default="context compacted (kept the last exchanges).")
        except Exception as e:  # noqa: BLE001
            return "❌ " + _i18n("gw.compact_fail", _default="compact failed: {e}", e=e)
