"""Transporte NATIVO Google Gemini (#12, port do Hermes agent/gemini_native_adapter.py).

Prontidão multi-vendor: o caminho OpenAI-compat do Gemini é historicamente frágil (auth churn, quirks
de tool-call, thought-signature). O caminho nativo (`generateContent`) é o canônico, menor latência, e
lida melhor com extended-thinking + structured output. Aqui mora a TRADUÇÃO (OpenAI-msgs ↔ Gemini),
testável sem rede; a chamada de SDK (`google-genai`) é lazy-import via lazy_deps('provider.gemini').

Hoje o Okami é assinatura-Claude; isto fica PRONTO p/ quando precisar trocar de vendor.
"""
from __future__ import annotations

from okami.llm.usage import Completion, normalize_usage

_FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}


def to_gemini_request(messages: list[dict], *, generation_config: dict | None = None) -> dict:
    """OpenAI-style messages → corpo do generateContent do Gemini.

    system → systemInstruction; user → 'user'; assistant → 'model'; tool/function → ignorado no MVP."""
    contents = []
    system_txt = []
    for m in messages or []:
        role = m.get("role")
        text = _text_of(m.get("content"))
        if role == "system":
            if text:
                system_txt.append(text)
            continue
        if role == "tool":
            continue
        grole = "model" if role == "assistant" else "user"
        contents.append({"role": grole, "parts": [{"text": text}]})
    req: dict = {"contents": contents}
    if system_txt:
        req["systemInstruction"] = {"parts": [{"text": "\n".join(system_txt)}]}
    if generation_config:
        req["generationConfig"] = generation_config
    return req


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                    # multimodal: extrai só os blocos de texto
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def from_gemini_response(resp: dict) -> tuple[str, str]:
    """resposta do Gemini → (texto, finish_reason normalizado)."""
    cands = (resp or {}).get("candidates") or []
    if not cands:
        return "", "stop"
    parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    finish = _FINISH.get((cands[0] or {}).get("finishReason", ""), "stop")
    return text, finish


def probe_gemini_tier(api_key: str, *, _get=None) -> str:
    """Best-effort: 'paid' | 'free' | 'unknown' p/ o limite de rate. Nunca levanta."""
    try:
        import urllib.request
        url = "https://generativelanguage.googleapis.com/v1beta/models?key=" + (api_key or "")
        getter = _get or (lambda u: urllib.request.urlopen(u, timeout=10).read())  # noqa: S310
        getter(url)
        return "paid"                                # alcançou a API com a chave → assume tier pago
    except Exception:  # noqa: BLE001
        return "unknown"


def gemini_native_complete(pc, messages: list[dict], model: str | None, overrides: dict | None = None) -> Completion:
    """Completa via SDK nativo do Gemini (google-genai). lazy_deps instala se faltar."""
    from okami.core.lazy_deps import ensure
    ensure("provider.gemini", prompt=False)
    from google import genai  # type: ignore

    key = getattr(pc, "api_key", None) or ""
    client = genai.Client(api_key=key)
    req = to_gemini_request(messages, generation_config=(overrides or {}).get("generation_config"))
    mdl = model or pc.model
    # google-genai: system_instruction + os params de geração vão DENTRO de `config`. Antes o systemInstruction
    # ia cru no kwarg `config` (errado) e o generationConfig sumia.
    config = dict(req.get("generationConfig") or {})
    sysi = req.get("systemInstruction")
    if sysi:
        config["system_instruction"] = (sysi.get("parts") or [{}])[0].get("text", "")
    resp = client.models.generate_content(model=mdl, contents=req["contents"], config=config or None)
    rd = resp if isinstance(resp, dict) else resp.to_dict()
    text, finish = from_gemini_response(rd)
    return Completion(text=text, finish_reason=finish, provider=pc.name, model=mdl,
                      usage=normalize_usage(rd.get("usageMetadata"), transport="gemini_native"))


__all__ = ["to_gemini_request", "from_gemini_response", "probe_gemini_tier", "gemini_native_complete"]
