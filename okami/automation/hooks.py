"""Event hooks / plugins (estilo OpenClaw/Hermes) — roda código nos pontos do ciclo de vida.

Eventos: `before_task`/`after_task`, `before_tool`/`after_tool`, `before_write`, `compaction`,
`cron_run`, `before_skill_install`. Um hook `before_*` pode VETAR (bloquear) retornando exit≠0 /
False — útil p/ políticas (ex.: barrar `run_shell` perigoso, barrar install de skill). Os `after_*`
são observadores (retorno ignorado).

Fontes de hook (todas opcionais, combináveis):
- **config** `hooks: { evento: ["comando shell", ...] }` (no okami.yaml/agent.yaml);
- **convenção de pasta** `hooks/<evento>/*` (scripts executáveis no projeto);
- **in-process** `hm.on(evento, fn)` (usado em testes e plugins Python).
O payload do evento vai pro comando via env `OKAMI_HOOK_PAYLOAD` (JSON) + stdin.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Callable

_BLOCKABLE = ("before_task", "before_tool", "before_write", "before_skill_install")


class HookManager:
    def __init__(self, config: dict | None = None, root: str = ".", *, runner: Callable | None = None,
                 emit: Callable[[str], None] = lambda m: None, include_builtin: bool = False):
        self.config = config or {}
        self.root = Path(root)
        self.emit = emit
        self.include_builtin = include_builtin     # plugins NATIVOS do pacote (o runner real liga; testes isolam)
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._run = runner or self._run_cmd

    def on(self, event: str, fn: Callable) -> None:
        """Registra um handler in-process (plugin Python / teste)."""
        self._handlers[event].append(fn)

    def _scripts(self, event: str) -> list[Path]:
        d = self.root / "hooks" / event
        scripts = sorted(p for p in d.glob("*") if p.is_file()) if d.exists() else []
        return [*scripts, *self._plugin_scripts(event)]

    def _plugin_scripts(self, event: str) -> list[Path]:
        """#14: plugin em `<root>/plugins/<nome>/hooks/<event>/*` contribui scripts de hook — é o que faz a
        DESCOBERTA virar EXECUÇÃO. + plugins NATIVOS do pacote (okami/builtin/plugins) quando include_builtin
        (o runner real liga). Dedup por nome: o plugin do projeto vence o nativo de mesmo nome."""
        bases = [self.root / "plugins"]
        if self.include_builtin:
            try:
                from okami.builtin import builtin_plugins_root
                bases.append(builtin_plugins_root())
            except Exception:  # noqa: BLE001 — nativos ausentes não derrubam os hooks
                pass
        out: list[Path] = []
        seen: set[str] = set()
        for base in bases:
            if not base.is_dir():
                continue
            for plugin in sorted(p for p in base.iterdir() if p.is_dir()):
                if plugin.name in seen:            # projeto (1ª base) vence o nativo de mesmo nome
                    continue
                seen.add(plugin.name)
                d = plugin / "hooks" / event
                if d.is_dir():
                    out += sorted(p for p in d.glob("*") if p.is_file())
        return out

    def _run_cmd(self, cmd: str, event: str, payload: dict) -> bool:
        """Roda um hook de shell; devolve True se passou (exit 0), False se vetou (exit≠0).

        Env SANITIZADO por padrão (P0.2): um hook versionado/injetado NÃO recebe os segredos do
        ambiente (mesma proteção do run_shell/MCP). Repasse explícito via hooks.env_passthrough."""
        from okami.core.tools import sanitized_env
        env = {**sanitized_env(), "OKAMI_HOOK_EVENT": event, "OKAMI_HOOK_PAYLOAD": json.dumps(payload)}
        for nm in (self.config or {}).get("env_passthrough") or []:    # allowlist explícita (ex.: GITHUB_TOKEN)
            if nm in os.environ:
                env[nm] = os.environ[nm]
        try:
            # hook = comando do operador (config confiável), não input do modelo.
            r = subprocess.run(  # nosec B602
                cmd, shell=True, cwd=str(self.root), env=env,  # noqa: S602  # nosemgrep — operador, não modelo
                input=json.dumps(payload), capture_output=True, text=True, timeout=30)
            if r.stdout.strip():
                self.emit(f"[hook {event}] {r.stdout.strip()[:200]}")
            return r.returncode == 0
        except Exception as e:  # noqa: BLE001 — hook que explode não derruba o agente
            self.emit(f"[hook {event}] erro: {e}")
            return True

    def fire(self, event: str, payload: dict | None = None) -> bool:
        """Dispara todos os hooks do evento. Devolve False se algum `before_*` VETOU."""
        payload = payload or {}
        ok = True
        for fn in self._handlers.get(event, []):
            try:
                if fn(payload) is False and event in _BLOCKABLE:
                    ok = False
            except Exception:  # noqa: BLE001
                pass
        for cmd in self.config.get(event, []) or []:
            if self._run(cmd, event, payload) is False and event in _BLOCKABLE:
                ok = False
        for script in self._scripts(event):
            if self._run(str(script), event, payload) is False and event in _BLOCKABLE:
                ok = False
        return ok

    def events(self) -> dict[str, int]:
        """Quantos hooks há por evento (config + pasta + in-process) — para `okami hooks`."""
        out: dict[str, int] = defaultdict(int)
        for ev, cmds in (self.config or {}).items():
            out[ev] += len(cmds or [])
        for ev, fns in self._handlers.items():
            out[ev] += len(fns)
        seen_events = set()
        base = self.root / "hooks"
        if base.exists():
            for d in base.iterdir():
                if d.is_dir():
                    seen_events.add(d.name)
        plug = self.root / "plugins"                       # #14: eventos vindos de plugin
        if plug.is_dir():
            for plugin in plug.iterdir():
                hd = plugin / "hooks"
                if hd.is_dir():
                    for d in hd.iterdir():
                        if d.is_dir():
                            seen_events.add(d.name)
        for ev in seen_events:
            out[ev] += len(self._scripts(ev))              # _scripts já soma pasta + plugins
        return dict(out)
