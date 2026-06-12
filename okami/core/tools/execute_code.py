"""execute_code — programmatic tool calling (pesquisa #5 item 30, Hermes execute_code).

A MAIOR economia de tokens da pesquisa: um script Python orquestra N leituras/agregações e só o
RESULTADO FINAL (stdout) volta pro contexto do modelo — os resultados intermediários das tools
ficam no script. O script roda em SUBPROCESSO (sys.executable -I, env sanitizado, cwd=workspace,
timeout com kill) e fala com o harness por um RPC de linha: `tool(name, **args)`.

Segurança (mesma classe de risco do run_shell — código arbitrário):
- RPC só com tools READ-ONLY (allowlist) — sem bypass de aprovação/grounding via script;
- perfil read-only bloqueia a tool inteira; caminho sensível no código é bloqueado (não-yolo);
- código com padrão perigoso (subprocess/socket/rmtree/…) é SENSÍVEL → go/no-go (approval.classify);
- superfície remota não recebe a tool (tool_policy _REMOTE_DENY + danger=dangerous).
"""
from __future__ import annotations

import json
import re
import subprocess
import threading

from okami.core.tools.base import _SENSITIVE_PATH, Tool, ToolResult

_RPC_MARK = "\x01OKAMI_RPC\x01"
RPC_ALLOWED = ("read_file", "list_dir", "find_files", "tool_search")   # leitura pura, sem aprovação
_MAX_RPC_CALLS = 100
_MAX_RPC_RESULT = 200_000          # por chamada, p/ DENTRO do script (não vai pro contexto)
_MAX_OUTPUT = 100_000              # stdout final (o budget do harness ainda corta/persiste depois)
_MAX_TIMEOUT = 300

# O runner é GENÉRICO (não interpola o código do usuário — vai por arquivo): define tool() e executa.
_RUNNER = r'''
import json, sys
_M = "\x01OKAMI_RPC\x01"
def tool(name, **args):
    sys.stdout.write(_M + json.dumps({"tool": name, "args": args}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("canal RPC fechado")
    resp = json.loads(line)
    if not resp.get("ok"):
        raise RuntimeError(str(resp.get("output", "tool falhou")))
    return resp.get("output", "")
_src = open(sys.argv[1], encoding="utf-8").read()
exec(compile(_src, "<execute_code>", "exec"), {"tool": tool, "__name__": "__main__"})
'''


class ExecuteCode(Tool):
    name = "execute_code"
    description = ("Roda um script Python que pode chamar tools de LEITURA via `tool(name, **args)` "
                   f"({', '.join(RPC_ALLOWED)}) e fazer qualquer agregação/filtragem em código. Os "
                   "resultados intermediários ficam NO SCRIPT — só o que você der print() volta. Use "
                   "p/ colapsar N leituras/contagens num passo só (ex.: ler 10 arquivos e somar). "
                   "Tools de escrita/shell NÃO existem aqui — use as tools normais p/ agir.")
    args_schema = {"code": "script Python (use tool('read_file', path=...) e print() do resultado)",
                   "timeout": "(opc) segundos até cortar — default 60, máx 300"}
    required = ("code",)

    def run(self, args, ctx):
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(False, "execute_code: 'code' precisa ser um script Python não-vazio.")
        mode = getattr(ctx.sandbox, "mode", "")
        if mode == "read-only":
            return ToolResult(False, "sandbox read-only: execute_code roda código arbitrário "
                              "(pode mutar estado) — bloqueado neste perfil.")
        if mode != "yolo" and _SENSITIVE_PATH.search(code):
            return ToolResult(False, "execute_code: o código toca caminho sensível (.env/.ssh/"
                              "credenciais/*.pem/*.key) — bloqueado p/ não vazar segredo.")
        try:
            to = max(1, min(int(args.get("timeout") or 60), _MAX_TIMEOUT))
        except (TypeError, ValueError):
            to = 60
        import sys
        import tempfile
        from pathlib import Path
        from okami.core.tools.base import sanitized_env
        with tempfile.TemporaryDirectory(prefix="okami-exec-") as td:
            runner = Path(td) / "runner.py"
            src = Path(td) / "code.py"
            runner.write_text(_RUNNER, encoding="utf-8")
            src.write_text(code, encoding="utf-8")
            proc = subprocess.Popen(                                    # noqa: S603 — risco gateado por
                [sys.executable, "-I", str(runner), str(src)],          # approval/policy/superfície
                cwd=str(ctx.workspace), env=sanitized_env(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1)
            timed_out = threading.Event()

            def _kill():
                timed_out.set()
                proc.kill()
            timer = threading.Timer(to, _kill)
            timer.start()
            out_parts: list[str] = []
            out_len = 0
            rpc_calls = 0
            try:
                for line in proc.stdout:                # RPC e prints chegam intercalados, em linha
                    if line.startswith(_RPC_MARK):
                        rpc_calls += 1
                        reply = self._serve_rpc(line[len(_RPC_MARK):], ctx, rpc_calls)
                        try:
                            proc.stdin.write(json.dumps(reply, ensure_ascii=False) + "\n")
                            proc.stdin.flush()
                        except (BrokenPipeError, OSError):
                            break
                        continue
                    if out_len < _MAX_OUTPUT:
                        out_parts.append(line)
                        out_len += len(line)
                proc.wait()
            finally:
                timer.cancel()
                if proc.poll() is None:
                    proc.kill()
            stderr = (proc.stderr.read() or "").strip()
        output = "".join(out_parts).rstrip()
        if out_len >= _MAX_OUTPUT:
            output += f"\n[… stdout cortado em {_MAX_OUTPUT} chars — imprima MENOS (agregue no script)]"
        if timed_out.is_set():
            return ToolResult(False, f"execute_code: timeout ({to}s) — script cortado. Saída até aqui:\n"
                              f"{output}", effect=True)
        if proc.returncode != 0:
            tail = "\n".join(stderr.splitlines()[-12:])
            return ToolResult(False, f"execute_code: exit={proc.returncode}\n{output}\n{tail}".strip(),
                              effect=True)
        return ToolResult(True, output or "(script terminou sem print — imprima o resultado)",
                          effect=True)

    @staticmethod
    def _serve_rpc(payload: str, ctx, n_call: int) -> dict:
        """Executa UMA chamada RPC do script: allowlist read-only + teto de chamadas/tamanho.
        Resposta {ok, output} — o erro vira exceção DENTRO do script (ele pode tratar)."""
        if n_call > _MAX_RPC_CALLS:
            return {"ok": False, "output": f"teto de {_MAX_RPC_CALLS} chamadas de tool atingido"}
        try:
            req = json.loads(payload)
            name = str(req.get("tool", ""))
            t_args = req.get("args") or {}
        except (ValueError, AttributeError):
            return {"ok": False, "output": "RPC malformado"}
        if name not in RPC_ALLOWED:
            return {"ok": False, "output": f"tool '{name}' não permitida no execute_code — só leitura: "
                    f"{', '.join(RPC_ALLOWED)}. Para escrever/rodar, use as tools normais."}
        reg = getattr(ctx, "registry", None) or {}
        tool = reg.get(name)
        if tool is None:
            from okami.core.tools import default_registry
            tool = default_registry().get(name)
        if tool is None:
            return {"ok": False, "output": f"tool '{name}' indisponível"}
        try:
            res = tool.run(t_args if isinstance(t_args, dict) else {}, ctx)
        except Exception as e:  # noqa: BLE001 — erro de tool vira exceção no script, não crash aqui
            return {"ok": False, "output": f"erro na tool {name}: {e}"}
        return {"ok": bool(res.ok), "output": (res.output or "")[:_MAX_RPC_RESULT]}


_PY_DANGER = re.compile(
    r"\bsubprocess\b|os\.(system|popen|exec[lv]p?e?|spawn|kill|remove|unlink|rmdir|renames?)\b|"
    r"shutil\.(rmtree|move)\b|\bsocket\b|\burllib\b|\brequests\b|http\.client|\bctypes\b|"
    r"\bpty\b|\bsignal\b|open\([^)]*,\s*['\"][wax]", re.I)


def code_is_dangerous(code: str) -> bool:
    """Padrão perigoso no script (rede/processo/deleção/escrita crua) → go/no-go (approval)."""
    return bool(_PY_DANGER.search(code or ""))
