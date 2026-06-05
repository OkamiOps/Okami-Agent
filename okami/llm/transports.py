"""Transports de provider — como a chamada chega ao modelo.

- litellm: padrão (api_key/api_base). Implementado em providers.py.
- claude_cli: dirige o CLI oficial `claude -p` (assinatura, OAuth/refresh cuidados pelo
  próprio CLI). Caminho SANCIONADO — reusar o token OAuth direto contra api.anthropic.com
  é restrito por ToS e quebra (Hermes #15080/#12905).
- codex_oauth: reusa ~/.codex/auth.json (tokens.access_token + account_id) contra
  chatgpt.com/backend-api/codex/responses. EXPERIMENTAL/não-verificado ao vivo.

Cada transport expõe `complete(pc, messages, model) -> str`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request

from okami.config import ProviderConfig
from okami.llm.usage import Completion, normalize_usage


def _split_model(pc: ProviderConfig, model: str | None) -> str:
    """Remove o prefixo de roteamento ('claude-subscription/x' -> 'x')."""
    m = model or pc.model
    return m.split("/", 1)[1] if "/" in m else m


def _text_of(content) -> str:
    """Conteúdo pode ser str ou lista multimodal (vision §6) — extrai só o texto p/ transports texto-only."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if any(isinstance(c, dict) and c.get("type") == "image_url" for c in content):
            bits.append("[imagem anexada — não visível neste transporte texto-only]")
        return " ".join(b for b in bits if b)
    return str(content)


def _flatten(messages: list[dict]) -> tuple[str, str]:
    """Separa o system e serializa o resto num transcript de prompt único."""
    system = ""
    parts: list[str] = []
    for m in messages:
        role, content = m.get("role", "user"), _text_of(m.get("content", ""))
        if role == "system" and not system:
            system = content
        else:
            parts.append(f"{role.upper()}: {content}")
    return system, "\n\n".join(parts)


# --------------------------------------------------------------------- claude_cli
def claude_binary() -> str | None:
    return shutil.which("claude")


# Esforço de raciocínio → diretiva de "extended thinking" do Claude (o CLI não tem flag de budget;
# a alavanca documentada é a convenção "think / think hard / ultrathink" no prompt).
_CLAUDE_THINK = {"minimal": "", "low": "", "medium": "think", "high": "think hard",
                 "xhigh": "think harder", "max": "ultrathink"}


def claude_cli_complete(pc: ProviderConfig, messages: list[dict], model: str | None,
                        overrides: dict | None = None) -> Completion:
    binary = claude_binary()
    if not binary:
        raise RuntimeError("CLI 'claude' não encontrado no PATH. Instale/logue o Claude Code.")
    model_short = _split_model(pc, model)
    system, transcript = _flatten(messages)
    # Instruções (system) + transcript vão juntos no prompt do -p (evita flags frágeis).
    prompt = (system + "\n\n" + transcript).strip() if system else transcript
    effort = (overrides or {}).get("reasoning_effort") or pc.reasoning_effort   # /think > default
    directive = _CLAUDE_THINK.get(effort, "")
    if directive:
        prompt = f"({directive})\n\n{prompt}"        # nudge de extended thinking p/ o Claude
    cmd = [binary, "-p", "--output-format", "json", "--model", model_short]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("claude -p timeout (300s)") from e
    if r.returncode != 0:
        raise RuntimeError(f"claude -p falhou (exit {r.returncode}): {r.stderr.strip()[:400]}")
    out = r.stdout.strip()
    try:
        obj = json.loads(out)
        # --output-format json: {"type":"result","result":"...","usage":{...}}
        text = obj.get("result") or obj.get("text") or out
        usage = normalize_usage(obj.get("usage"), transport="claude_cli")
        return Completion(text=text, usage=usage, provider=pc.name, model=model_short)
    except json.JSONDecodeError:
        return Completion(text=out, usage=normalize_usage(None, transport="claude_cli"),
                          provider=pc.name, model=model_short)


# --------------------------------------------------------------------- codex_oauth
CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"


# Eventos que ENCERRAM o stream da Responses API. Se o stream acabar sem nenhum deles E sem texto,
# foi uma queda/corte no meio → tem que LEVANTAR erro (não retornar "" silencioso), pra cair no
# failover/retry do complete_messages em vez de virar "violação de Action-or-Terminate" no harness.
_CODEX_TERMINAL = frozenset({"response.completed", "response.incomplete", "response.failed"})


def _codex_sse(lines) -> tuple[str, dict | None, list]:
    """Parseia o stream SSE da Responses API do Codex → (texto, usage).

    Texto: deltas `response.output_text.delta` (fallback: `output` do terminal). USAGE: capturado do
    evento terminal (`response.usage`) — keystone de custo, antes a gente jogava fora. Robustez (Hermes
    `codex_runtime`): exige TERMINAL; corte sem texto nem terminal → RuntimeError (vira retry/failover).
    """
    chunks: list[str] = []
    final = ""
    usage: dict | None = None
    saw_terminal = False
    incomplete_reason = ""
    calls: dict[str, dict] = {}     # function_call NATIVO (Onda 3): item_id -> {id, name, arguments}
    for raw in lines:
        line = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        t = obj.get("type", "")
        if t == "response.output_text.delta":
            chunks.append(obj.get("delta", ""))
        elif t in ("response.output_item.added", "response.output_item.done"):
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "function_call":
                iid = item.get("id") or item.get("call_id") or str(len(calls))
                calls[iid] = {"id": item.get("call_id") or item.get("id") or "",
                              "name": item.get("name", ""), "arguments": item.get("arguments", "") or ""}
        elif t == "response.function_call_arguments.delta":
            iid = obj.get("item_id") or ""
            if iid in calls:
                calls[iid]["arguments"] += obj.get("delta", "")
        elif t in _CODEX_TERMINAL:
            saw_terminal = True
            resp = obj.get("response") or {}
            usage = resp.get("usage") or usage                 # ← tokens (custo §A2)
            out = resp.get("output", []) or []
            texts = [
                c.get("text", "")
                for it in out if isinstance(it, dict)
                for c in (it.get("content") or [])
                if isinstance(c, dict) and c.get("type") in ("output_text", "text")
            ]
            for it in out:                       # function_call no array terminal (autoritativo)
                if isinstance(it, dict) and it.get("type") == "function_call":
                    iid = it.get("id") or it.get("call_id") or str(len(calls))
                    calls[iid] = {"id": it.get("call_id") or it.get("id") or "",
                                  "name": it.get("name", ""), "arguments": it.get("arguments", "") or ""}
            if texts:
                final = "".join(texts)
            if t == "response.failed":
                err = (resp or obj).get("error") or obj.get("error") or obj
                raise RuntimeError(f"codex stream falhou: {err}")
            if t == "response.incomplete":
                incomplete_reason = (resp.get("incomplete_details") or {}).get("reason", "") or "incompleto"
        elif t == "error":
            raise RuntimeError(f"codex stream erro: {obj.get('error') or obj}")
    text = "".join(chunks) or final
    tool_calls = [c for c in calls.values() if c.get("name")]
    if not text and not tool_calls:              # tool_call sem texto é resposta VÁLIDA (Onda 3)
        if not saw_terminal:
            raise RuntimeError("codex: stream encerrou sem evento terminal (resposta vazia)")
        if incomplete_reason:
            raise RuntimeError(f"codex: resposta incompleta sem texto ({incomplete_reason})")
    return text, usage, tool_calls


def _codex_sse_text(lines) -> str:
    """Só o texto (wrapper p/ compat/teste)."""
    return _codex_sse(lines)[0]


def _responses_tools(registry) -> list[dict]:
    """Schemas das tools no formato da Responses API do codex (function FLAT, sem o wrapper 'function')."""
    from okami.core.tools import openai_tools
    out = []
    for tdef in openai_tools(registry):
        fn = tdef.get("function", tdef)
        out.append({"type": "function", "name": fn.get("name", ""),
                    "description": fn.get("description", ""), "parameters": fn.get("parameters", {})})
    return out


def _toolcalls_to_action_text(tool_calls) -> str:
    """Converte o PRIMEIRO function_call nativo no protocolo de ação JSON-em-texto que o harness parseia."""
    tc = tool_calls[0]
    try:
        args = json.loads(tc.get("arguments") or "{}")
    except (json.JSONDecodeError, TypeError):
        args = {}
    block = json.dumps({"tool": tc.get("name", ""), "args": args}, ensure_ascii=False)
    return f"```json\n{block}\n```"


def codex_oauth_complete(pc: ProviderConfig, messages: list[dict], model: str | None,
                         overrides: dict | None = None) -> str:
    """Assinatura ChatGPT via Responses API do Codex, com token OAuth NATIVO do Okami.

    Login: `okami login codex` (device flow nativo, sem precisar do codex CLI).
    O endpoint EXIGE `store=false` + `stream=true` (só SSE) — verificado ao vivo.
    """
    from okami.llm import oauth
    access = oauth.codex_access_token()
    if not access:
        raise RuntimeError("Sem token Codex. Rode: okami login codex")
    account = oauth.codex_account_id()
    model_short = _split_model(pc, model)
    system, _ = _flatten(messages)
    input_items = [
        {"role": m["role"], "content": m["content"]}
        for m in messages if m.get("role") != "system"
    ]
    payload = {
        "model": model_short,
        "instructions": system,
        "input": input_items,
        "store": False,    # exigido pelo endpoint ("Store must be set to false")
        "stream": True,     # exigido pelo endpoint ("Stream must be set to true")
    }
    native = bool(getattr(pc, "native_tools", False))   # Onda 3 (opt-in): tool-calling nativo
    if native:
        from okami.core.tools import default_registry
        payload["tools"] = _responses_tools(default_registry())
        payload["tool_choice"] = "auto"
    effort = (overrides or {}).get("reasoning_effort") or pc.reasoning_effort  # /think > default do provider
    if effort:
        payload["reasoning"] = {"effort": effort}   # think effort (gpt-5/codex): minimal|low|medium|high
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(CODEX_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access}")
    if account:
        req.add_header("ChatGPT-Account-Id", account)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
            text, usage, tool_calls = _codex_sse(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"codex HTTP {e.code}: {detail}") from e
    if native and tool_calls:                    # function_call nativo → protocolo de ação (pipeline atual)
        text = _toolcalls_to_action_text(tool_calls)
    return Completion(text=text, tool_calls=tool_calls,
                      usage=normalize_usage(usage, transport="codex_oauth"),
                      provider=pc.name, model=model_short)


# --------------------------------------------------------------------- minimax_oauth
def minimax_oauth_complete(pc: ProviderConfig, messages: list[dict], model: str | None,
                           overrides: dict | None = None) -> Completion:
    """MiniMax via OAuth token plan: usa o access_token do store como bearer no LiteLLM."""
    from okami.llm import oauth
    token = oauth.get_valid_token(pc.name, pc.oauth)
    if not token:
        raise RuntimeError(f"Sem token OAuth para '{pc.name}'. Rode: okami login {pc.name}")
    import litellm

    kw: dict = {"model": model or pc.model, "messages": messages, "api_key": token}
    if pc.api_base:
        kw["api_base"] = pc.api_base
    kw.update(pc.params)
    resp = litellm.completion(**kw)
    return Completion(text=resp.choices[0].message.content or "",
                      usage=normalize_usage(getattr(resp, "usage", None), transport="litellm"),
                      provider=pc.name, model=model or pc.model)


def dispatch(pc: ProviderConfig, messages: list[dict], model: str | None,
             overrides: dict | None = None):
    """Resultado via transport não-litellm (`Completion`), ou None se for litellm (segue no LiteLLM)."""
    if pc.transport == "claude_cli":
        return claude_cli_complete(pc, messages, model, overrides)
    if pc.transport == "codex_oauth":
        return codex_oauth_complete(pc, messages, model, overrides)
    if pc.transport == "minimax_oauth":
        return minimax_oauth_complete(pc, messages, model, overrides)
    return None
