"""#12 Onda C: Blueprints — automação parametrizada com slots tipados (port Hermes cron/blueprint_catalog).

Fonte única → render no CLI (slash command), form (dashboard) e agente. fill_blueprint valida slots e
vira kwargs do cron Scheduler.add (sem 2º motor de job)."""
from __future__ import annotations

import pytest


def test_catalog_has_blueprints():
    from okami.automation.blueprints import CATALOG, get_blueprint
    assert CATALOG and "daily-briefing" in CATALOG
    assert get_blueprint("daily-briefing").title


def test_fill_blueprint_time_and_weekdays():
    from okami.automation.blueprints import fill_blueprint, get_blueprint
    bp = get_blueprint("daily-briefing")
    kw = fill_blueprint(bp, {"time": "09:30", "days": "weekdays"})
    assert kw["schedule"] == "30 9 * * 1-5"               # 09:30 em dias úteis
    assert "prompt" in kw and kw["prompt"]


def test_fill_blueprint_uses_defaults():
    from okami.automation.blueprints import fill_blueprint, get_blueprint
    bp = get_blueprint("daily-briefing")
    kw = fill_blueprint(bp, {})                            # sem slots → defaults
    assert kw["schedule"].endswith("* * *") or "*" in kw["schedule"]


def test_fill_blueprint_rejects_bad_enum():
    from okami.automation.blueprints import BlueprintFillError, fill_blueprint, get_blueprint
    bp = get_blueprint("daily-briefing")
    with pytest.raises(BlueprintFillError):
        fill_blueprint(bp, {"days": "marte-feira"})        # não é um preset válido


def test_fill_blueprint_rejects_bad_time():
    from okami.automation.blueprints import BlueprintFillError, fill_blueprint, get_blueprint
    bp = get_blueprint("daily-briefing")
    with pytest.raises(BlueprintFillError):
        fill_blueprint(bp, {"time": "25:99"})


def test_slash_command_render():
    from okami.automation.blueprints import blueprint_slash_command, get_blueprint
    cmd = blueprint_slash_command(get_blueprint("daily-briefing"))
    assert cmd.startswith("/blueprint daily-briefing") and "time=" in cmd


def test_form_schema_render():
    from okami.automation.blueprints import blueprint_form_schema, get_blueprint
    schema = blueprint_form_schema(get_blueprint("daily-briefing"))
    assert schema["key"] == "daily-briefing"
    assert any(f["name"] == "time" and f["type"] == "time" for f in schema["fields"])
