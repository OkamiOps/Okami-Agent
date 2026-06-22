"""Tools do harness — FACHADA do pacote (era tools.py monolítico).

Re-exporta tudo de base/files/memory/agentic/process/control/registry → quem fazia
`from okami.core.tools import X` (ToolContext/Tool/default_registry/RunShell/Process*/…) não muda.
"""
from __future__ import annotations

from okami.core.tools.agentic import Browse, GenerateImage, ManageSkill, Spawn, UseSkill
from okami.core.tools.base import (
    Tool, ToolContext, ToolResult, _SENSITIVE_ENV, _SENSITIVE_PATH, _SHELL_MUTATES, _SHELL_READONLY,
    _safe_path, openai_tools, sanitized_env, shell_has_effect,
)
from okami.core.tools.control import NeedInput, Respond, TaskBlocked, TaskComplete
from okami.core.tools.files import EditFile, FindFiles, ListDir, ReadFile, RunShell, WriteFile, _norm_name
from okami.core.tools.memory import FinishSetup, RecallMemory, RememberFact, RememberUser
from okami.core.tools.audio import AudioAnalyze
from okami.core.tools.speak import TextToSpeech
from okami.core.tools.notify import Notify, SendMessage
from okami.core.tools.clarify import Clarify
from okami.core.tools.suggest import SuggestAutomation
from okami.core.tools.todo import TodoWrite, render_pending
from okami.core.tools.secrets import StoreSecret
from okami.core.tools.remote import RemoteConnect, RemoteDisconnect
from okami.core.tools.process import (
    ProcessKill, ProcessList, ProcessLog, ProcessPoll, ProcessSignal, ProcessStart,
    ProcessWait, ProcessWrite,
)
from okami.core.tools.registry import default_registry

__all__ = [
    "Tool", "ToolContext", "ToolResult", "openai_tools", "sanitized_env", "shell_has_effect",
    "_safe_path", "_SENSITIVE_PATH", "_SENSITIVE_ENV", "_SHELL_MUTATES", "_SHELL_READONLY", "_norm_name",
    "ReadFile", "WriteFile", "EditFile", "ListDir", "FindFiles", "RunShell",
    "RememberFact", "RecallMemory", "RememberUser", "FinishSetup",
    "UseSkill", "ManageSkill", "Spawn", "Browse", "GenerateImage",
    "AudioAnalyze", "TextToSpeech", "Notify", "SendMessage", "Clarify", "SuggestAutomation", "TodoWrite", "render_pending", "StoreSecret",
    "RemoteConnect", "RemoteDisconnect",
    "ProcessStart", "ProcessWrite", "ProcessPoll", "ProcessWait", "ProcessLog", "ProcessList",
    "ProcessKill", "ProcessSignal",
    "Respond", "TaskComplete", "TaskBlocked", "NeedInput", "default_registry",
]
