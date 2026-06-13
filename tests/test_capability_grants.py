"""Capability grants — o DONO concede shell/process ao próprio agente remoto (fix do bug ao vivo).

O default seguro é remoto-sem-shell (deny-by-default). Mas o dono que roda o PRÓPRIO agente no
Telegram precisava de um jeito ergonômico de liberar — antes só `tools.surfaces.telegram.allow:[…]`
(indescobrível). Agora `tools.shell: true` (ou process/spawn) concede a capacidade. Opt-in EXPLÍCITO:
sem a chave, o default seguro fica. Aprovação/hardline/sandbox seguem valendo por cima.
"""
from __future__ import annotations

from okami.core.tool_policy import capability_warnings, denied, filter_registry


# ------------------------------------------------------------------ default seguro preservado
def test_default_telegram_denies_shell():
    cfg = {"fs": "home"}                              # exatamente o que o user tinha
    assert denied("telegram", "run_shell", config=cfg)
    assert denied("telegram", "execute_code", config=cfg)
    assert denied("telegram", "process_start", config=cfg)


def test_no_config_still_denies():
    assert denied("telegram", "run_shell", config=None)


# ------------------------------------------------------------------ grant shell
def test_shell_grant_unlocks_shell_family():
    cfg = {"fs": "home", "shell": True}
    for t in ("run_shell", "execute_code", "process_start", "process_write",
              "process_signal", "process_kill"):
        assert not denied("telegram", t, config=cfg), t


def test_shell_grant_does_not_unlock_spawn():
    assert denied("telegram", "spawn", config={"shell": True})


def test_process_grant_is_subset():
    cfg = {"process": True}
    assert not denied("telegram", "process_start", config=cfg)
    assert denied("telegram", "run_shell", config=cfg)        # process ≠ shell arbitrário
    assert denied("telegram", "execute_code", config=cfg)


def test_spawn_grant():
    assert not denied("telegram", "spawn", config={"spawn": True})


def test_falsy_grant_is_noop():
    assert denied("telegram", "run_shell", config={"shell": False})
    assert denied("telegram", "run_shell", config={"shell": 0})


# ------------------------------------------------------------------ explicit deny ainda vence
def test_explicit_surface_deny_overrides_grant():
    cfg = {"shell": True, "surfaces": {"telegram": {"deny": ["run_shell"]}}}
    assert denied("telegram", "run_shell", config=cfg)        # deny explícito > grant
    assert not denied("telegram", "execute_code", config=cfg)  # o resto do grant segue


# ------------------------------------------------------------------ CLI não é afetado
def test_cli_unaffected():
    assert not denied("cli", "run_shell", config={})


# ------------------------------------------------------------------ filter_registry integra
def test_filter_registry_includes_shell_when_granted():
    from okami.core.tools import default_registry
    reg = default_registry()
    without = filter_registry(reg, "telegram", config={"fs": "home"})
    withgrant = filter_registry(reg, "telegram", config={"fs": "home", "shell": True})
    assert "run_shell" not in without
    assert "run_shell" in withgrant and "execute_code" in withgrant


# ------------------------------------------------------------------ warning de boot
def test_warning_on_remote_shell_grant():
    warns = capability_warnings("telegram", {"shell": True})
    assert warns and any("shell" in w.lower() for w in warns)


def test_warning_louder_with_allow_all():
    warns = capability_warnings("telegram", {"shell": True}, allow_all=True)
    assert any("allow_all" in w.lower() or "qualquer" in w.lower() for w in warns)


def test_no_warning_without_grant():
    assert capability_warnings("telegram", {"fs": "home"}) == []


def test_no_warning_on_cli():
    assert capability_warnings("cli", {"shell": True}) == []   # CLI já é do dono — sem alarme
