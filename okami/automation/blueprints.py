"""Blueprints de automação — automação parametrizada com slots tipados (#12, port do Hermes
cron/blueprint_catalog.py).

Um blueprint é a definição em UM lugar de uma automação que cada superfície renderiza nativo: CLI/TUI
(slash command pré-preenchido), dashboard (form, 1 campo por slot), agente (preenche conversando).
Fonte única = o schema de slots. `fill_blueprint` valida e vira kwargs do cron `Scheduler.add` — sem 2º
motor de job. O dono nunca digita cron cru: a recorrência é fixa no template; só as partes humanas
(hora, dias) são parametrizadas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SLOT_TYPES = frozenset({"time", "enum", "text", "weekdays"})

WEEKDAY_PRESETS: dict[str, str] = {"everyday": "*", "weekdays": "1-5", "weekends": "0,6"}


class BlueprintFillError(ValueError):
    """Valor de slot inválido."""


@dataclass(frozen=True)
class BlueprintSlot:
    name: str
    type: str
    label: str
    default: object = None
    options: tuple = ()
    optional: bool = False
    help: str = ""

    def __post_init__(self):
        if self.type not in _SLOT_TYPES:
            raise ValueError(f"tipo de slot desconhecido {self.type!r} (slot {self.name})")


@dataclass(frozen=True)
class AutomationBlueprint:
    key: str
    title: str
    description: str
    schedule_template: str        # ex.: "{minute} {hour} * * {dow}"
    prompt: str
    slots: tuple = ()
    default_target: str = "home"


CATALOG: dict[str, AutomationBlueprint] = {}


def _register(bp: AutomationBlueprint) -> None:
    CATALOG[bp.key] = bp


_register(AutomationBlueprint(
    key="daily-briefing",
    title="Briefing diário",
    description="Resumo da manhã: agenda, e-mails importantes, novidades dos repos.",
    schedule_template="{minute} {hour} * * {dow}",
    prompt="Monte meu briefing da manhã: compromissos de hoje, e-mails que pedem ação, e o que mudou "
           "nos repositórios que acompanho. Conciso, em tópicos. Se não houver nada relevante, diga [SILENT].",
    slots=(
        BlueprintSlot("time", "time", "Horário", default="08:00", help="HH:MM"),
        BlueprintSlot("days", "weekdays", "Dias", default="everyday", options=tuple(WEEKDAY_PRESETS)),
    ),
))
_register(AutomationBlueprint(
    key="weekly-review",
    title="Revisão semanal",
    description="Retrospecto da semana + plano da próxima.",
    schedule_template="{minute} {hour} * * {dow}",
    prompt="Faça a retrospectiva da minha semana (o que andou, o que travou) e proponha as 3 prioridades "
           "da próxima. Baseie-se nas sessões e tarefas recentes.",
    slots=(
        BlueprintSlot("time", "time", "Horário", default="18:00", help="HH:MM"),
        BlueprintSlot("days", "weekdays", "Dia", default="weekends", options=tuple(WEEKDAY_PRESETS)),
    ),
))


def get_blueprint(key: str) -> AutomationBlueprint:
    if key not in CATALOG:
        raise KeyError(f"blueprint desconhecido: {key!r}")
    return CATALOG[key]


def _validate_time(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m:
        raise BlueprintFillError(f"horário inválido {value!r} — use HH:MM")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise BlueprintFillError(f"horário fora do intervalo: {value!r}")
    return hour, minute


def fill_blueprint(bp: AutomationBlueprint, values: dict) -> dict:
    """Valida `values` contra os slots e devolve kwargs p/ Scheduler.add: {schedule, prompt, target}."""
    values = values or {}
    subst: dict[str, str] = {}
    for slot in bp.slots:
        raw = values.get(slot.name, slot.default)
        if raw is None and not slot.optional:
            raise BlueprintFillError(f"slot obrigatório ausente: {slot.name}")
        if slot.type == "time":
            hour, minute = _validate_time(str(raw))
            subst["hour"], subst["minute"] = str(hour), str(minute)
        elif slot.type == "weekdays":
            if str(raw) not in WEEKDAY_PRESETS:
                raise BlueprintFillError(f"preset de dias inválido {raw!r} — use {', '.join(WEEKDAY_PRESETS)}")
            subst["dow"] = WEEKDAY_PRESETS[str(raw)]
        elif slot.type == "enum":
            if slot.options and str(raw) not in slot.options:
                raise BlueprintFillError(f"valor inválido p/ {slot.name}: {raw!r} (opções: {', '.join(slot.options)})")
            subst[slot.name] = str(raw)
        else:  # text
            subst[slot.name] = str(raw)
    schedule = bp.schedule_template
    for k, v in subst.items():
        schedule = schedule.replace("{" + k + "}", v)
    return {"schedule": schedule, "prompt": bp.prompt, "target": bp.default_target}


def blueprint_slash_command(bp: AutomationBlueprint) -> str:
    """Slash command pré-preenchido com os defaults: `/blueprint daily-briefing time=08:00 days=everyday`."""
    args = " ".join(f"{s.name}={s.default}" for s in bp.slots if s.default is not None)
    return f"/blueprint {bp.key} {args}".strip()


def blueprint_form_schema(bp: AutomationBlueprint) -> dict:
    """Schema p/ um renderer de form (dashboard): 1 campo por slot."""
    return {
        "key": bp.key, "title": bp.title, "description": bp.description,
        "fields": [{"name": s.name, "type": s.type, "label": s.label, "default": s.default,
                    "options": list(s.options), "optional": s.optional, "help": s.help} for s in bp.slots],
    }


__all__ = ["BlueprintSlot", "AutomationBlueprint", "CATALOG", "get_blueprint", "fill_blueprint",
           "blueprint_slash_command", "blueprint_form_schema", "BlueprintFillError", "WEEKDAY_PRESETS"]
