"""Transporte NATIVO Google Gemini (#12/#14, port do Hermes agent/gemini_native_adapter.py).

Prontidão multi-vendor: o caminho OpenAI-compat do Gemini é frágil (auth churn, quirks de tool-call,
thought-signature). O nativo (`generateContent`) é canônico, menor latência, melhor com tool-calling +
structured output. Aqui mora a TRADUÇÃO COMPLETA (mensagens, TOOLS/function-calling, tool-results), testável
sem rede; o SDK (`google-genai`) é lazy-import via lazy_deps('provider.gemini').

Hoje o Okami é assinatura-Claude; isto fica PRONTO p/ quando precisar trocar de vendor.
"""
from __future__ import annotations

import json

from okami.llm.usage import Completion, normalize_usage

_FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _content_parts(content) -> list[dict]:
    """Content OpenAI (str ou lista multimodal) → parts Gemini: text + inlineData/fileData p/ imagem."""
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []
    parts: list[dict] = []
    for p in content:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text" and p.get("text"):
            parts.append({"text": p["text"]})
        elif p.get("type") == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:   # data-uri → inlineData
                head, b64 = url.split(";base64,", 1)
                mime = head[5:] or "image/png"
                parts.append({"inlineData": {"mimeType": mime, "data": b64}})
            elif url.startswith("data:"):                       # data-uri malformado (sem ;base64,) → pula
                continue                                        # NÃO mandar pro fileData (API rejeita)
            elif url:
                parts.append({"fileData": {"fileUri": url}})     # http(s)/gs → fileData
    return parts


def _tool_to_gemini(tool: dict) -> dict:
    """Schema OpenAI {type:function, function:{name,description,parameters}} → functionDeclaration Gemini."""
    fn = tool.get("function") or tool
    return {"name": fn.get("name", ""), "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}}}


def to_gemini_request(messages: list[dict], *, tools: list | None = None, generation_config: dict | None = None) -> dict:
    """OpenAI-style messages (+tools) → corpo do generateContent. system→systemInstruction; assistant→model;
    tool-call do assistant→functionCall; mensagem role=tool→functionResponse."""
    contents = []
    system_txt = []
    for m in messages or []:
        role = m.get("role")
        if role == "system":
            t = _text_of(m.get("content"))
            if t:
                system_txt.append(t)
            continue
        if role == "tool":                            # resultado de tool → functionResponse
            contents.append({"role": "user", "parts": [{"functionResponse": {
                "name": m.get("name") or m.get("tool_call_id") or "tool",
                "response": {"result": _text_of(m.get("content"))}}}]})
            continue
        parts = _content_parts(m.get("content"))      # texto + imagem (inlineData/fileData)
        for tc in (m.get("tool_calls") or []):        # tool-call do assistant → functionCall
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            parts.append({"functionCall": {"name": fn.get("name", ""), "args": args}})
        if not parts:
            parts = [{"text": ""}]
        contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    req: dict = {"contents": contents}
    if system_txt:
        req["systemInstruction"] = {"parts": [{"text": "\n".join(system_txt)}]}
    if tools:
        req["tools"] = [{"functionDeclarations": [_tool_to_gemini(t) for t in tools]}]
    if generation_config:
        req["generationConfig"] = generation_config
    return req


def from_gemini_response(resp: dict) -> tuple[str, str, list]:
    """resposta do Gemini → (texto, finish_reason, tool_calls[{id,name,arguments}])."""
    cands = (resp or {}).get("candidates") or []
    if not cands:
        return "", "stop", []
    parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
    tool_calls = []
    for i, p in enumerate(parts):
        fc = p.get("functionCall") if isinstance(p, dict) else None
        if fc:
            tool_calls.append({"id": fc.get("name", "") + f"_{i}", "name": fc.get("name", ""),
                               "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False)})
    finish = "tool_calls" if tool_calls else _FINISH.get((cands[0] or {}).get("finishReason", ""), "stop")
    return text, finish, tool_calls


def probe_gemini_tier(api_key: str, *, _get=None) -> str:
    """Best-effort: 'paid' | 'unknown' p/ o limite de rate. Nunca levanta."""
    try:
        import urllib.request
        url = "https://generativelanguage.googleapis.com/v1beta/models?key=" + (api_key or "")
        getter = _get or (lambda u: urllib.request.urlopen(u, timeout=10).read())  # noqa: S310
        getter(url)
        return "paid"
    except Exception:  # noqa: BLE001
        return "unknown"


def gemini_native_complete(pc, messages: list[dict], model: str | None, overrides: dict | None = None) -> Completion:
    """Completa via SDK nativo do Gemini (google-genai). lazy_deps instala se faltar."""
    key = getattr(pc, "api_key", None) or ""
    if not key:                                       # erro CLARO antes do SDK (ValueError opaco do genai)
        raise RuntimeError(f"provider '{getattr(pc, 'name', '?')}' (gemini_native) precisa de api_key — "
                           "configure GEMINI_API_KEY ou providers.<nome>.api_key")
    from okami.core.lazy_deps import ensure
    ensure("provider.gemini", prompt=False)
    from google import genai  # type: ignore

    ov = overrides or {}
    client = genai.Client(api_key=key)
    req = to_gemini_request(messages, tools=ov.get("tools"), generation_config=ov.get("generation_config"))
    mdl = model or pc.model
    config = dict(req.get("generationConfig") or {})
    sysi = req.get("systemInstruction")
    if sysi:
        config["system_instruction"] = (sysi.get("parts") or [{}])[0].get("text", "")
    if req.get("tools"):
        config["tools"] = req["tools"]
    resp = client.models.generate_content(model=mdl, contents=req["contents"], config=config or None)
    rd = resp if isinstance(resp, dict) else resp.to_dict()
    text, finish, tool_calls = from_gemini_response(rd)
    return Completion(text=text, finish_reason=finish, tool_calls=tool_calls, provider=pc.name, model=mdl,
                      usage=normalize_usage(rd.get("usageMetadata"), transport="gemini_native"))


__all__ = ["to_gemini_request", "from_gemini_response", "probe_gemini_tier", "gemini_native_complete"]
