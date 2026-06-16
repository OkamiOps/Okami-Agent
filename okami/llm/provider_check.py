"""Self-test de CAPACIDADE dos transportes nativos (score→100, sem rede/SDK).

Valida o round-trip de tradução de um transporte nativo (Gemini/Bedrock): monta um payload sintético
com texto + imagem + tools, traduz pro formato nativo, e extrai um tool-call de uma resposta sintética.
Prova que a CAPACIDADE está completa (texto, function-calling, imagem) — a validação em TRÁFEGO real
ainda precisa da chave do dono, mas a tradução não fica por testar. Usado por `okami provider check`.
"""
from __future__ import annotations


def check_native_transport(transport: str) -> dict:
    """Devolve {ok, text, tools, image, tool_call} — cada flag indica se aquela capacidade traduz certo."""
    msgs = [
        {"role": "system", "content": "seja conciso"},
        {"role": "user", "content": [
            {"type": "text", "text": "o que é isto?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
    ]
    tools = [{"type": "function", "function": {"name": "run_shell", "description": "roda",
              "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]
    rep = {"ok": False, "transport": transport, "text": False, "tools": False, "image": False, "tool_call": False}
    try:
        if transport == "gemini_native":
            from okami.llm.gemini_native import from_gemini_response, to_gemini_request
            req = to_gemini_request(msgs, tools=tools)
            parts = req["contents"][-1]["parts"]
            rep["text"] = any("text" in p for p in parts)
            rep["image"] = any("inlineData" in p for p in parts)
            rep["tools"] = bool(req.get("tools"))
            _t, _f, tcs = from_gemini_response({"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "run_shell", "args": {"cmd": "ls"}}}]}}]})
            rep["tool_call"] = bool(tcs) and tcs[0]["name"] == "run_shell"
        elif transport == "bedrock_native":
            from okami.llm.bedrock_native import from_converse_response, to_converse_request
            req = to_converse_request(msgs, tools=tools)
            blocks = req["messages"][-1]["content"]
            rep["text"] = any("text" in b for b in blocks)
            rep["image"] = any("image" in b for b in blocks)
            rep["tools"] = bool(req.get("toolConfig"))
            _t, _f, tcs = from_converse_response({"output": {"message": {"content": [
                {"toolUse": {"toolUseId": "t1", "name": "run_shell", "input": {"cmd": "ls"}}}]}},
                "stopReason": "tool_use"})
            rep["tool_call"] = bool(tcs) and tcs[0]["name"] == "run_shell"
        else:
            return rep
    except Exception as e:  # noqa: BLE001
        rep["error"] = str(e)[:160]
        return rep
    rep["ok"] = rep["text"] and rep["tools"] and rep["image"] and rep["tool_call"]
    return rep


def credentials_present(transport: str, pc=None) -> tuple[bool, str]:
    """A credencial p/ um transporte nativo está disponível? Devolve (presente, motivo). NUNCA loga/devolve
    o valor da credencial — só se existe e de onde viria."""
    import os
    if transport == "gemini_native":
        key = (getattr(pc, "api_key", "") or os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY") or "")
        return (bool(key), "api_key/GEMINI_API_KEY presente" if key else "sem api_key (GEMINI_API_KEY/GOOGLE_API_KEY)")
    if transport == "bedrock_native":                    # cadeia de credencial AWS (env/SSO/role)
        present = any(os.environ.get(k) for k in (
            "AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE"))
        return (present, "credencial AWS na env" if present else "sem credencial AWS (env/SSO/role)")
    return (False, "transporte não-nativo")


def live_check_transport(transport: str, *, pc=None, _caller=None) -> dict:
    """Validação EM TRÁFEGO real: faz uma chamada mínima de verdade ao vendor se a credencial existe; senão
    PULA com graça (skipped=True, não falha). `_caller(msgs)->Completion` injetável p/ teste sem rede."""
    rep = {"transport": transport, "ok": False, "live": False, "skipped": False}
    present, why = credentials_present(transport, pc)
    rep["reason"] = why
    if not present:
        rep["skipped"] = True
        return rep
    msgs = [{"role": "user", "content": "responda exatamente com a palavra: pong"}]
    try:
        if _caller is not None:
            comp = _caller(msgs)
        elif transport == "gemini_native":
            from okami.llm.gemini_native import gemini_native_complete
            comp = gemini_native_complete(pc, msgs, getattr(pc, "model", None))
        elif transport == "bedrock_native":
            from okami.llm.bedrock_native import bedrock_native_complete
            comp = bedrock_native_complete(pc, msgs, getattr(pc, "model", None))
        else:
            rep["reason"] = "transporte não-nativo"
            return rep
        text = (getattr(comp, "text", "") or "")
        rep["live"] = True
        rep["ok"] = bool(text.strip())
        rep["text"] = text[:80]
    except Exception as e:  # noqa: BLE001 — erro real (403/quota/rede) → reporta, não derruba a CLI
        rep["error"] = str(e)[:200]
    return rep


__all__ = ["check_native_transport", "credentials_present", "live_check_transport"]
