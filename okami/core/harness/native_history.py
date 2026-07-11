"""Atomic history helpers for native function-call turns."""
from __future__ import annotations

from okami.core.harness.parsing import _oai_tool_call


def _call_id(call: dict) -> str:
    function = call.get("function") or {}
    return str(call.get("id") or function.get("id") or "")


def append_native_assistant(messages: list[dict], calls: list[dict], *, content=None) -> dict:
    message = {"role": "assistant", "content": content,
               "tool_calls": [_oai_tool_call(call) for call in calls]}
    messages.append(message)
    return message


def append_native_tool_result(messages: list[dict], call_id: str, content: str, *, ok: bool = True) -> dict:
    value = content if ok else f"REJECTED: {content}"
    message = {"role": "tool", "tool_call_id": call_id, "content": value}
    messages.append(message)
    return message


def native_history_groups(messages: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            i += 1
            continue
        group = [message]
        ids = {_call_id(tc) for tc in message["tool_calls"]}
        i += 1
        while i < len(messages) and messages[i].get("role") == "tool":
            if messages[i].get("tool_call_id") not in ids:
                break
            group.append(messages[i])
            i += 1
        groups.append(group)
    return groups


def repair_native_history(messages: list[dict], *, interrupted: bool = False) -> list[dict]:
    """Keep complete native groups; drop incomplete groups or close them as interrupted on resume."""
    out: list[dict] = []
    i = 0
    while i < len(messages):
        message = messages[i]
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if not calls:
            if message.get("role") != "tool":
                out.append(message)
            i += 1
            continue
        ids = [_call_id(tc) for tc in calls]
        group = [message]
        i += 1
        while i < len(messages) and messages[i].get("role") == "tool":
            if messages[i].get("tool_call_id") not in ids:
                break
            group.append(messages[i])
            i += 1
        answered = {m.get("tool_call_id") for m in group[1:]}
        if len(answered) == len(ids) and all(cid in answered for cid in ids):
            out.extend(group)
        elif interrupted:
            out.extend(group)
            for cid in ids:
                if cid not in answered:
                    out.append({"role": "tool", "tool_call_id": cid,
                                "content": "INTERRUPTED: native tool call was interrupted; do not re-execute."})
        # incomplete groups are intentionally omitted outside resume
    return out


__all__ = ["append_native_assistant", "append_native_tool_result", "native_history_groups",
           "repair_native_history"]
