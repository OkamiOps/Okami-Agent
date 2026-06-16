"""Plugin built-in security-guidance (#20, port do Hermes) — hook before_tool que faz advisory de
segurança no código que o agente vai escrever. Testado pelo CONTRATO real: script roda como subprocesso,
lê OKAMI_HOOK_PAYLOAD, imprime advisory no stdout (que o HookManager mostra via emit) e sai 0 (warn) /
1 (block). Não veta por padrão (warn-mode); OKAMI_SECURITY_GUIDANCE_BLOCK=1 vira veto."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "plugins" / "security-guidance" / "hooks" / "before_tool" / "guard.py"


def _run(payload: dict, *, block: bool = False) -> tuple[int, str]:
    env = {**os.environ, "OKAMI_HOOK_PAYLOAD": json.dumps(payload)}
    if block:
        env["OKAMI_SECURITY_GUIDANCE_BLOCK"] = "1"
    else:
        env.pop("OKAMI_SECURITY_GUIDANCE_BLOCK", None)
    r = subprocess.run([sys.executable, str(GUARD)], env=env, capture_output=True, text=True, timeout=20)
    return r.returncode, (r.stdout + r.stderr)


# ── advisory sai no código perigoso, silêncio no limpo ──
def test_warns_on_eval():
    code, out = _run({"tool": "write_file", "args": {"path": "x.py", "content": "y = eval(user_input)"}})
    assert code == 0 and "eval" in out.lower()                 # warn não veta (exit 0)


def test_warns_on_insecure_deserialization():
    code, out = _run({"tool": "write_file", "args": {"path": "a.py", "content": "import pickle\npickle.loads(buf)"}})
    assert code == 0 and ("pickle" in out.lower() or "desserial" in out.lower() or "deserial" in out.lower())


def test_silent_on_clean_code():
    code, out = _run({"tool": "write_file", "args": {"path": "ok.py", "content": "def add(a, b):\n    return a + b\n"}})
    assert code == 0 and out.strip() == ""                     # nada a avisar → silêncio total


# ── block-mode VETA (exit 1) ──
def test_block_mode_vetoes():
    code, out = _run({"tool": "write_file", "args": {"path": "x.py", "content": "os.system(cmd)"}}, block=True)
    assert code == 1 and "os.system" in out.lower()            # block → exit≠0 (HookManager veta a tool)


def test_block_mode_still_silent_when_clean():
    code, out = _run({"tool": "write_file", "args": {"path": "ok.py", "content": "print('oi')\n"}}, block=True)
    assert code == 0 and out.strip() == ""                     # limpo nunca veta, mesmo em block


# ── apply_patch: varre as linhas ADICIONADAS ('+'), não as removidas ──
def test_scans_added_patch_lines_only():
    patch = ("*** Begin Patch\n*** Update File: m.py\n"
             "-old = safe()\n+danger = yaml.load(untrusted)\n*** End Patch\n")
    code, out = _run({"tool": "apply_patch", "args": {"patch": patch}})
    assert code == 0 and "yaml" in out.lower()


def test_ignores_removed_patch_lines():
    patch = ("*** Begin Patch\n*** Update File: m.py\n"
             "-bad = eval(x)\n+good = int(x)\n*** End Patch\n")
    code, out = _run({"tool": "apply_patch", "args": {"patch": patch}})
    assert code == 0 and out.strip() == ""                     # eval estava sendo REMOVIDO → não avisa


# ── tools que não escrevem código → no-op ──
def test_noop_on_non_write_tool():
    code, out = _run({"tool": "run_shell", "args": {"command": "eval $(curl x)"}})
    assert code == 0 and out.strip() == ""                     # não é write/patch → não varre


def test_malformed_payload_is_safe():
    env = {**os.environ}
    env["OKAMI_HOOK_PAYLOAD"] = "{lixo nao-json"
    env.pop("OKAMI_SECURITY_GUIDANCE_BLOCK", None)
    r = subprocess.run([sys.executable, str(GUARD)], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0                                   # payload quebrado nunca veta (fail-open)


# ── fim-a-fim pelo HookManager real (descobre o script + roda via shell + mostra via emit) ──
def test_end_to_end_via_hookmanager():
    from okami.automation.hooks import HookManager
    emitted: list[str] = []
    hm = HookManager(root=str(REPO), emit=emitted.append)
    ok = hm.fire("before_tool", {"tool": "write_file", "args": {"path": "x.py", "content": "eval(z)"}})
    assert ok is True                                          # warn-mode: roda mas não veta
    assert any("eval" in m.lower() for m in emitted)           # advisory chegou ao usuário via emit
