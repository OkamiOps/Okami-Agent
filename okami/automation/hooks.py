"""Event hooks / plugins (estilo OpenClaw/Hermes) — roda código nos pontos do ciclo de vida.

Eventos: `before_task`/`after_task`, `before_tool`/`after_tool`, `before_write`, `compaction`,
`cron_run`, `before_skill_install`, `transform_tool_result`. Um hook `before_*` pode VETAR (bloquear)
retornando exit≠0 / False — útil p/ políticas (ex.: barrar `run_shell` perigoso, barrar install de
skill). Os `after_*` são observadores (retorno ignorado). `transform_tool_result` é NÃO-BLOQUEANTE
(porta do Hermes `transform_tool_result`/security-guidance): recebe (tool, args, result) e pode devolver
texto EXTRA a anexar ao resultado da tool — o modelo vê no PRÓXIMO turno e se auto-corrige, sem vetar
nem incomodar o dono ANTES da escrita. Múltiplos hooks compõem (texto concatenado); um hook que quebra
é isolado (nunca derruba o loop nem os outros hooks).

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
            # FAIL-CLOSED em evento de BLOQUEIO (paridade Hermes): um before_* de política/segurança que
            # erra (timeout/interpretador ruim/OOM) NÃO pode liberar a ação que existe pra barrar → veta.
            # Evento observador (after_*) não gateia nada → erro não tem efeito (segue True).
            return event not in _BLOCKABLE

    def _run_capture(self, cmd: str, event: str, payload: dict) -> str:
        """Como `_run_cmd`, mas devolve o STDOUT (texto a possivelmente anexar) em vez de bool — usado por
        eventos de TRANSFORMAÇÃO (`transform_tool_result`), que nunca vetam, só sugerem texto extra. Mesmo
        env sanitizado do `_run_cmd`; erro/timeout vira string vazia (fail-open, nunca derruba o hook)."""
        from okami.core.tools import sanitized_env
        env = {**sanitized_env(), "OKAMI_HOOK_EVENT": event, "OKAMI_HOOK_PAYLOAD": json.dumps(payload)}
        for nm in (self.config or {}).get("env_passthrough") or []:
            if nm in os.environ:
                env[nm] = os.environ[nm]
        try:
            r = subprocess.run(  # nosec B602
                cmd, shell=True, cwd=str(self.root), env=env,  # noqa: S602  # nosemgrep — operador, não modelo
                input=json.dumps(payload), capture_output=True, text=True, timeout=30)
            return r.stdout.strip()
        except Exception as e:  # noqa: BLE001 — hook que explode não derruba o resultado da tool
            self.emit(f"[hook {event}] erro: {e}")
            return ""

    def transform_tool_result(self, tool: str, args: dict, result_text: str) -> str:
        """Roda os hooks `transform_tool_result` (NÃO-bloqueante, port do Hermes): cada handler in-process
        ou script (pasta/plugin/config) recebe {tool, args, result} e pode devolver texto EXTRA, que é
        ANEXADO ao resultado (nunca substitui, nunca veta). Isolado por hook — try/except individual
        (handler in-process) / subprocess isolado (script) — um hook ruim não derruba os outros nem o
        loop (paridade com o `invoke_hook` do Hermes). Múltiplos hooks compõem em sequência."""
        event = "transform_tool_result"
        payload = {"tool": tool, "args": args, "result": result_text}
        text = result_text
        for fn in self._handlers.get(event, []):
            try:
                extra = fn(payload)
            except Exception as e:  # noqa: BLE001 — handler que explode não derruba a tool nem os outros hooks
                self.emit(f"[hook {event}] erro do handler: {e}")
                continue
            if extra:
                text = f"{text}\n\n{extra}" if text else str(extra)
        _cmds = self.config.get(event, []) or []
        if isinstance(_cmds, str):
            _cmds = [_cmds]
        for cmd in _cmds:
            extra = self._run_capture(cmd, event, payload)
            if extra:
                text = f"{text}\n\n{extra}" if text else extra
        for script in self._scripts(event):
            extra = self._run_capture(str(script), event, payload)
            if extra:
                text = f"{text}\n\n{extra}" if text else extra
        return text

    def fire(self, event: str, payload: dict | None = None) -> bool:
        """Dispara todos os hooks do evento. Devolve False se algum `before_*` VETOU."""
        payload = payload or {}
        ok = True
        for fn in self._handlers.get(event, []):
            try:
                if fn(payload) is False and event in _BLOCKABLE:
                    ok = False
            except Exception as e:  # noqa: BLE001 — handler que explode num evento de BLOQUEIO VETA (paridade
                self.emit(f"[hook {event}] erro do handler: {e}")    # com _run): política que erra não pode
                if event in _BLOCKABLE:                              # LIBERAR a ação que existe pra barrar
                    ok = False
        _cmds = self.config.get(event, []) or []
        if isinstance(_cmds, str):                      # config errada (string em vez de lista) → trata como UM
            _cmds = [_cmds]                             # comando (senão itera char-a-char e quebra a política)
        for cmd in _cmds:
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
