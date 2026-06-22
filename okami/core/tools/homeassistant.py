"""Tool homeassistant (#19) — controla/consulta o Home Assistant. Config-driven; domínios perigosos
bloqueados; chamar serviço é AÇÃO sensível (go/no-go via danger=sensitive no registro)."""
from __future__ import annotations

import json

from okami.core.tools.base import Tool, ToolResult


class HomeAssistant(Tool):
    name = "homeassistant"
    description = ("Home Assistant: action=list (entidades, opc domain) | state (entity_id) | call "
                   "(domain+service+data, ex.: light/turn_on). Precisa de integrations.homeassistant. "
                   "Domínios que rodam código (shell_command/python_script) são bloqueados.")
    args_schema = {"action": "list | state | call", "entity_id": "(state) ex.: light.sala",
                   "domain": "(list/call) ex.: light", "service": "(call) ex.: turn_on",
                   "data": "(call) dict de parâmetros (JSON)"}
    required = ("action",)

    def check(self) -> str | None:
        """Poda limpa sem integração configurada (senão o agente chama e leva RuntimeError em runtime)."""
        try:
            from okami.config import load_config
            from okami.integrations.homeassistant import ha_config
            if ha_config(load_config()) is None:
                return "Home Assistant não configurado — configure integrations.homeassistant.{url, token_env} no okami.yaml"
        except Exception:  # noqa: BLE001 — erro ao ler config não poda (fail-open)
            return None
        return None

    def run(self, args, ctx):
        cfg = getattr(ctx, "cfg", None)
        action = str(args.get("action") or "").strip().lower()
        from okami.integrations import homeassistant as ha
        try:
            if action == "list":
                out = ha.list_entities(cfg, domain=args.get("domain") or None)
                brief = [{"entity_id": s.get("entity_id"), "state": s.get("state")} for s in (out or [])[:60]]
                return ToolResult(True, json.dumps(brief, ensure_ascii=False), effect=False)
            if action == "state":
                ent = args.get("entity_id") or ""
                return ToolResult(True, json.dumps(ha.get_state(cfg, ent), ensure_ascii=False), effect=False)
            if action == "call":
                data = args.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        data = {}
                out = ha.call_service(cfg, args.get("domain") or "", args.get("service") or "", data or {})
                return ToolResult(True, json.dumps(out, ensure_ascii=False)[:2000], effect=True)
            return ToolResult(False, "homeassistant: action deve ser list | state | call.")
        except (ValueError, RuntimeError) as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"homeassistant falhou: {e}")
