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
import urllib.request

from okami.config import ProviderConfig


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


def claude_cli_complete(pc: ProviderConfig, messages: list[dict], model: str | None) -> str:
    binary = claude_binary()
    if not binary:
        raise RuntimeError("CLI 'claude' não encontrado no PATH. Instale/logue o Claude Code.")
    model_short = _split_model(pc, model)
    system, transcript = _flatten(messages)
    # Instruções (system) + transcript vão juntos no prompt do -p (evita flags frágeis).
    prompt = (system + "\n\n" + transcript).strip() if system else transcript
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
        # --output-format json: {"type":"result","result":"...", ...}
        return obj.get("result") or obj.get("text") or out
    except json.JSONDecodeError:
        return out


# --------------------------------------------------------------------- codex_oauth
CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"


def codex_oauth_complete(pc: ProviderConfig, messages: list[dict], model: str | None) -> str:
    """Assinatura ChatGPT via Responses API do Codex, com token OAuth NATIVO do Okami.

    Login: `okami login codex` (device flow nativo, sem precisar do codex CLI).
    Schema do endpoint a confirmar ao vivo — não chamamos isto em testes/dev automático.
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
    body = json.dumps({
        "model": model_short,
        "instructions": system,
        "input": input_items,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(CODEX_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access}")
    if account:
        req.add_header("ChatGPT-Account-Id", account)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    # Responses API: tenta extrair o texto de saída de formatos comuns.
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    out = data.get("output") or []
    chunks: list[str] = []
    for item in out:
        for c in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                chunks.append(c.get("text", ""))
    return "".join(chunks) or json.dumps(data)[:2000]


# --------------------------------------------------------------------- minimax_oauth
def minimax_oauth_complete(pc: ProviderConfig, messages: list[dict], model: str | None) -> str:
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
    return resp.choices[0].message.content or ""


def dispatch(pc: ProviderConfig, messages: list[dict], model: str | None) -> str | None:
    """Retorna o texto via transport não-litellm, ou None se for litellm (segue no LiteLLM)."""
    if pc.transport == "claude_cli":
        return claude_cli_complete(pc, messages, model)
    if pc.transport == "codex_oauth":
        return codex_oauth_complete(pc, messages, model)
    if pc.transport == "minimax_oauth":
        return minimax_oauth_complete(pc, messages, model)
    return None
