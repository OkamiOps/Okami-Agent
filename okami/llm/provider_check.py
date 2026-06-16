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


__all__ = ["check_native_transport"]
