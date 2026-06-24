"""Testes dos event hooks (§11): disparo, veto de before_*, fontes (config/in-process)."""

from __future__ import annotations

from okami.automation.hooks import HookManager


def test_in_process_handler_fires_with_payload():
    seen = []
    hm = HookManager()
    hm.on("after_task", lambda p: seen.append(p["state"]))
    assert hm.fire("after_task", {"state": "COMPLETE"}) is True
    assert seen == ["COMPLETE"]


def test_before_hook_can_veto():
    hm = HookManager()
    hm.on("before_tool", lambda p: False)              # veta
    assert hm.fire("before_tool", {"tool": "run_shell"}) is False


def test_after_hook_return_is_ignored():
    hm = HookManager()
    hm.on("after_tool", lambda p: False)               # after_* não bloqueia
    assert hm.fire("after_tool", {"tool": "x"}) is True


def test_config_command_runs_and_vetoes(tmp_path):
    calls = []

    def fake_run(cmd, event, payload):
        calls.append((cmd, event, payload["tool"]))
        return cmd != "deny"                           # "deny" → veta

    # root isolado: senão a fire() descobriria os plugins reais do repo (security-guidance/disk-cleanup)
    # e o runner injetado também rodaria os scripts deles, poluindo `calls`.
    hm = HookManager({"before_tool": ["log", "deny"]}, root=str(tmp_path), runner=fake_run)
    assert hm.fire("before_tool", {"tool": "write_file"}) is False     # algum comando vetou
    assert [c[0] for c in calls] == ["log", "deny"]


def test_handler_exception_fail_closed_on_blockable():
    hm = HookManager()
    hm.on("before_task", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hm.fire("before_task", {"goal": "x"}) is False  # before_* que explode VETA (fail-closed, igual ao shell)


def test_handler_exception_observer_event_stays_true():
    hm = HookManager()
    hm.on("after_task", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hm.fire("after_task", {"goal": "x"}) is True    # after_* não gateia nada → erro não veta


def test_string_config_treated_as_single_command():
    ran = []
    hm = HookManager(config={"before_tool": "exit 1"},     # STRING (config errada) — não pode iterar char-a-char
                     runner=lambda cmd, ev, pl: ran.append(cmd) or False)
    assert hm.fire("before_tool", {}) is False             # roda 'exit 1' como UM comando e veta
    assert ran == ["exit 1"]


def test_dir_convention_scripts(tmp_path):
    (tmp_path / "hooks" / "after_task").mkdir(parents=True)
    (tmp_path / "hooks" / "after_task" / "notify.sh").write_text("echo hi", encoding="utf-8")
    ran = []
    hm = HookManager(root=str(tmp_path), runner=lambda cmd, ev, pl: ran.append(cmd) or True)
    hm.fire("after_task", {})
    assert any("notify.sh" in c for c in ran)          # pegou o script da pasta


def test_events_counts_all_sources(tmp_path):
    hm = HookManager({"before_task": ["a", "b"]}, root=str(tmp_path))
    hm.on("after_tool", lambda p: None)
    ev = hm.events()
    assert ev["before_task"] == 2 and ev["after_tool"] == 1
