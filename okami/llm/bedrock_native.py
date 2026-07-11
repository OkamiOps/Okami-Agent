"""Transporte NATIVO AWS Bedrock via Converse API (#12/#14, port do Hermes agent/bedrock_adapter.py).

Prontidão multi-vendor: o Converse nativo usa a cadeia de credencial AWS (IAM role/SSO/env) — sem API
key. Aqui mora a TRADUÇÃO COMPLETA (mensagens, TOOLS/toolConfig, toolUse/toolResult), testável sem boto3/
rede; o client é lazy-import via lazy_deps('provider.bedrock').
"""
from __future__ import annotations

import json
import math

from okami.llm.usage import Completion, normalize_usage

_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
         "tool_use": "tool_calls", "content_filtered": "content_filter"}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _content_blocks(content) -> list[dict]:
    """Content OpenAI → blocos Converse: {text} + {image:{format,source:{bytes}}} p/ imagem data-uri."""
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []
    blocks: list[dict] = []
    for p in content:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text" and p.get("text"):
            blocks.append({"text": p["text"]})
        elif p.get("type") == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:
                import base64
                head, b64 = url.split(";base64,", 1)
                mime = head[5:] or "image/png"
                fmt = mime.split("/")[-1].replace("jpg", "jpeg")
                try:
                    blocks.append({"image": {"format": fmt, "source": {"bytes": base64.b64decode(b64)}}})
                except Exception:  # noqa: BLE001
                    pass
    return blocks


def _tool_to_bedrock(tool: dict) -> dict:
    fn = tool.get("function") or tool
    return {"toolSpec": {"name": fn.get("name", ""), "description": fn.get("description", ""),
                         "inputSchema": {"json": fn.get("parameters") or {"type": "object", "properties": {}}}}}


def to_converse_request(messages: list[dict], *, tools: list | None = None) -> dict:
    """OpenAI-style messages (+tools) → corpo do Converse. system separado; tool-call→toolUse;
    role=tool→toolResult."""
    conv_messages = []
    system = []
    for m in messages or []:
        role = m.get("role")
        if role == "system":
            t = _text_of(m.get("content"))
            if t:
                system.append({"text": t})
            continue
        if role == "tool":                            # resultado de tool → toolResult (numa msg 'user')
            conv_messages.append({"role": "user", "content": [{"toolResult": {
                "toolUseId": m.get("tool_call_id") or m.get("name") or "tool",
                "content": [{"text": _text_of(m.get("content"))}]}}]})
            continue
        blocks = _content_blocks(m.get("content"))    # texto + imagem (data-uri → bytes)
        for tc in (m.get("tool_calls") or []):        # tool-call do assistant → toolUse
            fn = tc.get("function") or {}
            try:
                inp = json.loads(fn.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                inp = {}
            blocks.append({"toolUse": {"toolUseId": tc.get("id", ""), "name": fn.get("name", ""), "input": inp}})
        if not blocks:
            blocks = [{"text": ""}]
        conv_messages.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})
    req: dict = {"messages": conv_messages}
    if system:
        req["system"] = system
    if tools:
        req["toolConfig"] = {"tools": [_tool_to_bedrock(t) for t in tools]}
    return req


def from_converse_response(resp: dict) -> tuple[str, str, list]:
    """resposta do Converse → (texto, finish_reason, tool_calls[{id,name,arguments}])."""
    blocks = (((resp or {}).get("output") or {}).get("message") or {}).get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b)
    tool_calls = []
    for b in blocks:
        tu = b.get("toolUse") if isinstance(b, dict) else None
        if tu:
            tool_calls.append({"id": tu.get("toolUseId", ""), "name": tu.get("name", ""),
                               "arguments": json.dumps(tu.get("input") or {}, ensure_ascii=False)})
    finish = _STOP.get((resp or {}).get("stopReason", ""), "stop")
    return text, finish, tool_calls


def bedrock_native_complete(pc, messages: list[dict], model: str | None, overrides: dict | None = None) -> Completion:
    """Completa via boto3 Converse. lazy_deps instala boto3 se faltar; credencial vem da cadeia AWS."""
    from okami.core.lazy_deps import ensure
    ensure("provider.bedrock", prompt=False)
    import boto3  # type: ignore

    ov = overrides or {}
    region = (pc.params or {}).get("region") or "us-east-1"
    client_kw = {"region_name": region}
    if ov.get("timeout") is not None:
        # botocore's read_timeout is the supported socket-level bound for Converse;
        # do not put a vendor-specific timeout field into the request payload.
        from botocore.config import Config
        if isinstance(ov["timeout"], bool):
            raise ValueError("timeout must be finite and strictly positive")
        timeout = float(ov["timeout"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and strictly positive")
        client_kw["config"] = Config(read_timeout=timeout)
    client = boto3.client("bedrock-runtime", **client_kw)
    req = to_converse_request(messages, tools=ov.get("tools"))
    mdl = model or pc.model
    kw: dict = {"modelId": mdl, "messages": req["messages"]}
    if req.get("system"):
        kw["system"] = req["system"]
    if req.get("toolConfig"):
        kw["toolConfig"] = req["toolConfig"]
    resp = client.converse(**kw)
    text, finish, tool_calls = from_converse_response(resp)
    return Completion(text=text, finish_reason=finish, tool_calls=tool_calls, provider=pc.name, model=mdl,
                      usage=normalize_usage(resp.get("usage"), transport="bedrock_native"))


__all__ = ["to_converse_request", "from_converse_response", "bedrock_native_complete"]
