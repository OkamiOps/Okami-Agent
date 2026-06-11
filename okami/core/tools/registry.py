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
from okami.core.tools.process import (
    ProcessKill, ProcessList, ProcessLog, ProcessPoll, ProcessSignal, ProcessStart,
    ProcessWait, ProcessWrite,
)


def default_registry() -> dict[str, Tool]:
    tools = [Respond(), ReadFile(), WriteFile(), EditFile(), ListDir(), FindFiles(),
             MakeDir(), MovePath(), CopyPath(), DeletePath(), RunShell(),
             ProcessStart(), ProcessPoll(), ProcessWait(), ProcessLog(), ProcessKill(), ProcessList(),
             ProcessWrite(), ProcessSignal(),
             RememberFact(), RecallMemory(), RememberUser(), UseSkill(), ManageSkill(), Spawn(),
             Browse(), GenerateImage(),
             FinishSetup(), TaskComplete(), TaskBlocked(), NeedInput()]
    return {t.name: t for t in tools}
