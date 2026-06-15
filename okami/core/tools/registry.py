"""default_registry — monta o registro de tools do harness (#14)."""
from __future__ import annotations

from okami.core.tools.agentic import Browse, GenerateImage, ManageSkill, Spawn, UseSkill
from okami.core.tools.base import Tool
from okami.core.tools.control import NeedInput, Respond, TaskBlocked, TaskComplete
from okami.core.tools.files import (
    CopyPath, DeletePath, EditFile, FindFiles, ListDir, MakeDir, MovePath, ReadFile,
    RunShell, WriteFile,
)
from okami.core.tools.memory import FinishSetup, RecallMemory, RememberFact, RememberUser
from okami.core.tools.execute_code import ExecuteCode
from okami.core.tools.search import SearchFiles
from okami.core.tools.session_search import SessionSearch
from okami.core.tools.patch import ApplyPatch
from okami.core.tools.toolsearch import ToolSearch
from okami.core.tools.websearch import WebSearch
from okami.core.tools.webextract import WebExtract
from okami.core.tools.vision import VisionAnalyze
from okami.core.tools.audio import AudioAnalyze
from okami.core.tools.notify import Notify
from okami.core.tools.clarify import Clarify
from okami.core.tools.suggest import SuggestAutomation
from okami.core.tools.todo import TodoWrite
from okami.core.tools.secrets import StoreSecret
from okami.core.tools.remote import RemoteConnect, RemoteDisconnect
from okami.core.tools.schedule import ScheduleJob
from okami.core.tools.process import (
    ProcessKill, ProcessList, ProcessLog, ProcessPoll, ProcessSignal, ProcessStart,
    ProcessWait, ProcessWrite,
)


def default_registry() -> dict[str, Tool]:
    tools = [Respond(), ReadFile(), WriteFile(), EditFile(), ApplyPatch(), ListDir(), FindFiles(),
             SearchFiles(), MakeDir(), MovePath(), CopyPath(), DeletePath(), RunShell(), ExecuteCode(),
             ProcessStart(), ProcessPoll(), ProcessWait(), ProcessLog(), ProcessKill(), ProcessList(),
             ProcessWrite(), ProcessSignal(),
             ScheduleJob(),
             RememberFact(), RecallMemory(), RememberUser(), SessionSearch(),
             UseSkill(), ManageSkill(), Spawn(),
             Browse(), WebSearch(), WebExtract(), GenerateImage(), VisionAnalyze(), AudioAnalyze(),
             ToolSearch(), Notify(), Clarify(), SuggestAutomation(), TodoWrite(), StoreSecret(),
             RemoteConnect(), RemoteDisconnect(),
             FinishSetup(), TaskComplete(), TaskBlocked(), NeedInput()]
    return {t.name: t for t in tools}
