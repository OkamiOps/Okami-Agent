"""Transporte NATIVO AWS Bedrock via Converse API (#12, port do Hermes agent/bedrock_adapter.py).

Prontidão multi-vendor: usuários AWS (EC2/EKS, Claude via Bedrock) hoje passam por shim OpenAI-compat
com latência/atrito de protocolo + exposição de chave. O Converse nativo usa a cadeia de credencial AWS
(IAM role/SSO/env) — sem armazenar API key. Aqui mora a TRADUÇÃO (OpenAI-msgs ↔ Converse), testável sem
boto3/rede; o client é lazy-import via lazy_deps('provider.bedrock').

Fica PRONTO p/ quando precisar (hoje o Okami é assinatura-Claude).
"""
from __future__ import annotations

from okami.llm.usage import Completion, normalize_usage

_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
         "tool_use": "tool_calls", "content_filtered": "content_filter"}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def to_converse_request(messages: list[dict]) -> dict:
    """OpenAI-style messages → corpo do Converse (messages + system separados; content em blocos)."""
    conv_messages = []
    system = []
    for m in messages or []:
        role = m.get("role")
        text = _text_of(m.get("content"))
        if role == "system":
            if text:
                system.append({"text": text})
            continue
        if role == "tool":
            continue
        crole = "assistant" if role == "assistant" else "user"
        conv_messages.append({"role": crole, "content": [{"text": text}]})
    req: dict = {"messages": conv_messages}
    if system:
        req["system"] = system
    return req


def from_converse_response(resp: dict) -> tuple[str, str]:
    """resposta do Converse → (texto, finish_reason normalizado)."""
    blocks = (((resp or {}).get("output") or {}).get("message") or {}).get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    finish = _STOP.get((resp or {}).get("stopReason", ""), "stop")
    return text, finish


def bedrock_native_complete(pc, messages: list[dict], model: str | None, overrides: dict | None = None) -> Completion:
    """Completa via boto3 Converse. lazy_deps instala boto3 se faltar; credencial vem da cadeia AWS."""
    from okami.core.lazy_deps import ensure
    ensure("provider.bedrock", prompt=False)
    import boto3  # type: ignore

    region = (pc.params or {}).get("region") or "us-east-1"
    client = boto3.client("bedrock-runtime", region_name=region)
    req = to_converse_request(messages)
    mdl = model or pc.model
    kw: dict = {"modelId": mdl, "messages": req["messages"]}
    if req.get("system"):
        kw["system"] = req["system"]
    resp = client.converse(**kw)
    text, finish = from_converse_response(resp)
    return Completion(text=text, finish_reason=finish, provider=pc.name, model=mdl,
                      usage=normalize_usage(resp.get("usage"), transport="bedrock_native"))


__all__ = ["to_converse_request", "from_converse_response", "bedrock_native_complete"]
