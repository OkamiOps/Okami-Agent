"""Backends de desktop p/ o computer-use. macOS nativo (screencapture + cliclick) é o primário (zero-dep,
auditável); pyautogui (via lazy_deps) é o fallback cross-platform. None se nenhum disponível → a tool sai
do registro (check_fn). Nunca levanta no `available()`.
"""
from __future__ import annotations

import shutil
import subprocess  # noqa: S404 — binários fixos de automação local (cliclick/screencapture), sem shell


def _which(name: str) -> str | None:
    return shutil.which(name)


class MacBackend:
    """screencapture (screenshot) + cliclick (mouse/teclado). Só no macOS com cliclick instalado."""

    def available(self) -> bool:
        import sys
        return sys.platform == "darwin" and _which("screencapture") is not None and _which("cliclick") is not None

    def screenshot(self, path: str) -> str:
        subprocess.run([_which("screencapture") or "screencapture", "-x", path],  # noqa: S603
                       check=False, timeout=20)
        return path

    def act(self, action: str, args: dict) -> None:
        cc = _which("cliclick") or "cliclick"
        if action in ("click", "right_click", "double_click", "move"):
            x, y = int(args["x"]), int(args["y"])
            verb = {"click": "c", "right_click": "rc", "double_click": "dc", "move": "m"}[action]
            subprocess.run([cc, f"{verb}:{x},{y}"], check=False, timeout=10)  # noqa: S603
        elif action == "type":
            subprocess.run([cc, "t:" + str(args.get("text", ""))], check=False, timeout=20)  # noqa: S603
        elif action == "key":
            # cliclick: modificadores via kd/ku, tecla via kp:<nome>. Combo "cmd+c" → kd:cmd kp:c ku:cmd.
            parts = [p.strip().lower() for p in str(args.get("keys", "")).split("+") if p.strip()]
            mods = [p for p in parts if p in ("cmd", "ctrl", "alt", "shift", "fn")]
            keys = [p for p in parts if p not in ("cmd", "ctrl", "alt", "shift", "fn")] or ["return"]
            argv = [cc]
            for m in mods:
                argv.append(f"kd:{m}")
            for k in keys:
                argv.append(f"kp:{k}")
            for m in reversed(mods):
                argv.append(f"ku:{m}")
            subprocess.run(argv, check=False, timeout=10)  # noqa: S603
        elif action == "scroll":
            # cliclick não rola; usa AppleScript via osascript (best-effort) — amount em "linhas"
            amt = int(args.get("amount", args.get("y", 3)))
            subprocess.run(["osascript", "-e",  # noqa: S603,S607
                            f'tell application "System Events" to scroll {{0, {amt}}}'],
                           check=False, timeout=10)


class PyAutoGuiBackend:
    """Fallback cross-platform via pyautogui (lazy-install)."""

    def available(self) -> bool:
        try:
            from okami.core import lazy_deps
            return "desktop.pyautogui" in lazy_deps.LAZY_DEPS and not lazy_deps.feature_missing("desktop.pyautogui")
        except Exception:  # noqa: BLE001
            return False

    def _gui(self):
        from okami.core.lazy_deps import ensure
        ensure("desktop.pyautogui", prompt=False)
        import pyautogui  # type: ignore
        return pyautogui

    def screenshot(self, path: str) -> str:
        self._gui().screenshot(path)
        return path

    def act(self, action: str, args: dict) -> None:
        g = self._gui()
        if action == "click":
            g.click(int(args["x"]), int(args["y"]))
        elif action == "right_click":
            g.rightClick(int(args["x"]), int(args["y"]))
        elif action == "double_click":
            g.doubleClick(int(args["x"]), int(args["y"]))
        elif action == "move":
            g.moveTo(int(args["x"]), int(args["y"]))
        elif action == "type":
            g.typewrite(str(args.get("text", "")), interval=0.01)
        elif action == "key":
            keys = [p.strip().lower() for p in str(args.get("keys", "")).split("+") if p.strip()]
            g.hotkey(*keys) if len(keys) > 1 else g.press(keys[0] if keys else "enter")
        elif action == "scroll":
            g.scroll(int(args.get("amount", args.get("y", 3))))


def get_backend():
    """Backend disponível (macOS nativo > pyautogui), ou None. Nunca levanta."""
    try:
        mac = MacBackend()
        if mac.available():
            return mac
        py = PyAutoGuiBackend()
        if py.available():
            return py
    except Exception:  # noqa: BLE001
        return None
    return None


__all__ = ["MacBackend", "PyAutoGuiBackend", "get_backend"]
