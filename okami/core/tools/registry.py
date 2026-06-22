"""default_registry — monta o registro de tools do harness (#14)."""
from __future__ import annotations

from okami.core.tools.agentic import (
    Browse, GenerateImage, InstallSkill, ManageSkill, Spawn, SpawnJobs, UseSkill,
)
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
from okami.core.tools.mixture import MixtureOfAgents
from okami.core.tools.video import GenerateVideo
from okami.core.tools.x_search import XSearch
from okami.core.tools.homeassistant import HomeAssistant
from okami.core.tools.feishu import FeishuDocRead
from okami.core.tools.computer_use import ComputerUse
from okami.core.tools.patch import ApplyPatch
from okami.core.tools.toolsearch import ToolSearch
from okami.core.tools.websearch import WebSearch
from okami.core.tools.webextract import WebExtract
from okami.core.tools.vision import VisionAnalyze
from okami.core.tools.audio import AudioAnalyze
from okami.core.tools.speak import TextToSpeech
from okami.core.tools.notify import Notify, SendMessage
from okami.core.tools.clarify import Clarify
from okami.core.tools.suggest import SuggestAutomation
from okami.core.tools.todo import TodoWrite
from okami.core.tools.secrets import StoreSecret
from okami.core.tools.provision import GitAuth, SshIdentity
from okami.core.tools.sysops import EnvCheck, RestartGateway, SystemMonitor
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
             UseSkill(), ManageSkill(), InstallSkill(), Spawn(), SpawnJobs(), MixtureOfAgents(),
             Browse(), WebSearch(), WebExtract(), GenerateImage(), GenerateVideo(), VisionAnalyze(), AudioAnalyze(), TextToSpeech(),
             XSearch(), HomeAssistant(), FeishuDocRead(), ComputerUse(),
             ToolSearch(), Notify(), SendMessage(), Clarify(), SuggestAutomation(), TodoWrite(), StoreSecret(),
             SshIdentity(), GitAuth(), RemoteConnect(), RemoteDisconnect(),
             SystemMonitor(), EnvCheck(), RestartGateway(),
             FinishSetup(), TaskComplete(), TaskBlocked(), NeedInput()]
    return {t.name: t for t in tools}
