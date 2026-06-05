"""Testes do gateway (sessões + slash commands + concorrência + go/no-go), canal fake."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from okami.agents import AgentSpec
from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint, build_endpoints


class FakeChannel(Channel):
    name = "fake"

    def __init__(self, token=None, allow_chats=None, allow_all=False):
        self.sent: list[tuple[str, str]] = []
        self.allow = {str(c) for c in (allow_chats or [])}
        self.allow_all = bool(allow_all)

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return not self.allow or str(chat_id) in self.allow


def _ok_task(goal):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"feito: {goal}"
    return t


def _runner_ok(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
    return _ok_task(goal)


def _ep(mode="manual", allow=None, runner=_runner_ok, spawn=None):
    import tempfile
    ch = FakeChannel(allow_chats=allow)
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                         approval_mode=mode, spawn=spawn or (lambda fn: fn()))   # ws isolado: persistência


def test_background_runs_isolated_and_reports():
    ep = _ep()
    ep.handle("7", "/background analise o repo")
    texts = [t for _, t in ep.channel.sent]
    assert any("background #1 rodando" in t for t in texts)
    assert any("background #1 pronto" in t and "feito: analise o repo" in t for t in texts)
    assert ep._bg == {}                                  # terminou → removido do tracking
    assert not any("analise o repo" in h for _, h in ep.session("7").history)   # não poluiu a sessão


def test_background_alias_and_requires_prompt():
    ep = _ep()
    ep.handle("7", "/background")
    assert any("uso: /background" in t for _, t in ep.channel.sent)
    ep.handle("7", "/bg some os numeros")                # alias /bg canonicaliza p/ background
    assert any("background #1 pronto" in t and "feito: some os numeros" in t for _, t in ep.channel.sent)


def test_title_sets_shows_in_status_and_persists():
    ep = _ep()
    ep.handle("7", "/title meu projeto okami")
    assert any("renomeada: meu projeto okami" in t for _, t in ep.channel.sent)
    ep.handle("7", "/status")
    assert any("📝 meu projeto okami" in t for _, t in ep.channel.sent)
    del ep.sessions["7"]                                 # força rebuild do store (persistência)
    assert ep.session("7").title == "meu projeto okami"


def test_message_runs_task_and_replies():
    ep = _ep()
    ep.handle("7", "crie x")
    texts = [t for _, t in ep.channel.sent]
    assert any("pensando" in t for t in texts)
    assert any("feito: crie x" in t for t in texts)   # papo: resposta limpa, sem selo ✅ robótico


def test_genesis_block_injected_on_first_contact_then_gone(tmp_path):
    """1ª conversa de um agente novo → bloco de gênese no contexto; selado → some."""
    captured = {}

    def runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        captured["ctx"] = extra_context
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "oi!"
        return t

    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=FakeChannel(), run_task=runner,
                       approval_mode="manual", spawn=lambda fn: fn())
    ep.handle("1", "oi")
    assert "PRIMEIRO CONTATO" in captured["ctx"]               # gênese conduz o 1º papo
    (tmp_path / ".okami").mkdir(exist_ok=True)
    (tmp_path / ".okami" / "genesis.done").write_text("done\n", encoding="utf-8")
    ep.handle("1", "e aí")
    assert "PRIMEIRO CONTATO" not in captured["ctx"]           # selado → não onboarda de novo


def test_on_event_threaded_into_run_task(tmp_path):
    """O chat liga progresso ao vivo: AgentEndpoint(on_event=…) chega no run_task."""
    captured = {}

    def runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, on_event=None, **kw):
        captured["on_event"] = on_event
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    sink = []

    def my_on_event(e):
        sink.append(e)

    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=FakeChannel(), run_task=runner,
                       approval_mode="manual", spawn=lambda fn: fn(), on_event=my_on_event)
    (tmp_path / ".okami").mkdir(exist_ok=True)
    (tmp_path / ".okami" / "genesis.done").write_text("done\n", encoding="utf-8")   # pula gênese
    ep.handle("1", "oi")
    assert captured["on_event"] is my_on_event          # progresso threadado pro harness


def test_real_task_keeps_completion_seal():
    """Tarefa de verdade (passo com efeito) MANTÉM o ✅ — só o papo casual perde o selo."""
    from okami.core import Step

    def runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "arquivo criado"
        t.steps = [Step(1, "write_file", {}, "ok", effect=True)]   # houve trabalho real
        return t

    ep = _ep(runner=runner)
    ep.handle("7", "crie x")
    texts = [t for _, t in ep.channel.sent]
    assert any(t.startswith("✅") and "arquivo criado" in t for t in texts)


def test_session_history_continuity():
    ep = _ep()
    ep.handle("7", "oi")
    ep.handle("7", "de novo")
    assert len(ep.session("7").history) == 4   # 2 trocas (user+agente)


def test_slash_new_resets_history():
    ep = _ep()
    ep.handle("7", "oi")
    ep.handle("7", "/new")
    assert ep.session("7").history == [] and "reiniciada" in ep.channel.sent[-1][1]


def test_slash_yolo_and_status():
    ep = _ep()
    ep.handle("7", "/yolo")
    assert ep.session("7").yolo is True
    ep.handle("7", "/status")
    assert "yolo=on" in ep.channel.sent[-1][1]


def test_unauthorized_chat():
    ep = _ep(allow=["1"])
    ep.handle("999", "oi")
    assert "não autorizado" in ep.channel.sent[-1][1]


def test_concurrency_busy_guard():
    ep = _ep(spawn=lambda fn: None)   # não roda → fica busy
    ep.handle("7", "tarefa1")
    ep.handle("7", "tarefa2")
    assert any("processando" in t for _, t in ep.channel.sent)


def test_approval_yolo_session_auto():
    ep = _ep(mode="manual")
    s = ep.session("7")
    s.yolo = True
    assert ep._approve("7", s)({"reason": "editar .env", "risk": "high"}) is True


def test_approval_smart_low_risk_auto():
    ep = _ep(mode="smart")
    assert ep._approve("7", ep.session("7"))({"reason": "x", "risk": "low"}) is True


def test_approval_over_chat_no():
    ep = _ep(mode="manual")
    s = ep.session("7")
    out = {}

    def w():
        out["ok"] = ep._approve("7", s)({"reason": "rm -rf", "risk": "critical"})

    th = threading.Thread(target=w)
    th.start()
    for _ in range(100):
        if "7" in ep._pending:
            break
        time.sleep(0.01)
    ep.handle("7", "/no")
    th.join(timeout=3)
    assert out["ok"] is False


def test_build_endpoints_only_agents_with_token():
    specs = {
        "a": AgentSpec("a", Path("."), {"channels": {"telegram": {"token": "X"}}}),
        "b": AgentSpec("b", Path("."), {}),
    }
    graw = {"default_provider": "lmstudio", "providers": {"lmstudio": {"model": "openai/x", "api_key": "k"}}}
    eps = build_endpoints(graw, specs, make_channel=FakeChannel, run_task=_runner_ok)
    assert [e.agent_id for e in eps] == ["a"]


# ----------------------------------------------------------------- GROUP (§10 turn-taking) ----------
from okami.channels.base import Inbound          # noqa: E402
from okami.gateway import GroupEndpoint          # noqa: E402
from okami.agents.group import GroupRoom, Member        # noqa: E402


class FakeGroupChannel:
    name = "fake-group"

    def __init__(self, allow_chats=None):
        self.inbox: list[Inbound] = []
        self.sent: list[tuple[str, str, str]] = []   # (agent_id, chat_id, text)
        self.started = False
        self.allow = {str(c) for c in (allow_chats or [])}

    def start(self):
        self.started = True

    def feed(self, chat_id, text):
        self.inbox.append(Inbound("fake", str(chat_id), text=text))

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def send_as(self, agent_id, chat_id, text):
        self.sent.append((agent_id, str(chat_id), text))

    def allowed(self, chat_id):
        return not self.allow or str(chat_id) in self.allow


def _six_bot_room():
    ids = ["cto", "ui", "backend", "data", "qa", "devops"]
    members = [Member(i, role=i) for i in ids]

    def moderator(history, candidates, mentioned):
        cids = {c.id for c in candidates}
        who, txt = history[-1]
        if who == "USER" and "bootstrap" in txt.lower() and "cto" in cids:
            return "cto"
        if who == "cto" and "ui" in cids:      # UI/UX reage ao CTO sobre Bootstrap
            return "ui"
        return None                            # mais ninguém → silêncio

    def responder(m, history):
        return {"cto": "bora de Bootstrap então",
                "ui": "melhor ShadCN/HeroUI (tokens, a11y)"}.get(m.id, "PASS")

    return GroupRoom(members, moderator, responder, cooldown=2)


def test_group_six_bots_only_relevant_reply_then_silence(tmp_path):
    ch = FakeGroupChannel()
    ep = GroupEndpoint(_six_bot_room(), ch, store_root=str(tmp_path))
    ch.feed("-100", "CTO, quero usar Bootstrap no frontend")
    ep.poll_once()
    assert [a for a, _, _ in ch.sent] == ["cto", "ui"]        # só 2 dos 6 falam (sem stampede)
    ep.room.select_speaker = lambda h, c, m: None             # nada novo a dizer
    ch.feed("-100", "beleza, valeu")
    ep.poll_once()
    assert [a for a, _, _ in ch.sent] == ["cto", "ui"]        # silêncio: nada novo enviado


def test_group_mention_forces_specific_bot(tmp_path):
    room = _six_bot_room()
    room.select_speaker = lambda h, c, m: (c[0].id if m else None)   # só fala se mencionado
    room.respond = lambda m, h: f"{m.id} aqui"
    ch = FakeGroupChannel()
    ep = GroupEndpoint(room, ch, store_root=str(tmp_path))
    ch.feed("-100", "@qa consegue validar isso?")
    ep.poll_once()
    assert ch.sent and ch.sent[0][0] == "qa"                 # menção força o bot certo


def test_group_endpoint_respects_allowlist(tmp_path):
    ch = FakeGroupChannel(allow_chats=["-100"])
    ep = GroupEndpoint(_six_bot_room(), ch, store_root=str(tmp_path))
    assert ep.handle("-999", "CTO, Bootstrap?") == []        # chat fora da allowlist → ignora
    assert ch.sent == []


def test_group_history_persists_across_restart(tmp_path):
    # 1º gateway: uma conversa no grupo
    ch1 = FakeGroupChannel()
    ep1 = GroupEndpoint(_six_bot_room(), ch1, store_root=str(tmp_path))
    ch1.feed("-100", "CTO, quero usar Bootstrap no frontend")
    ep1.poll_once()
    assert [a for a, _, _ in ch1.sent] == ["cto", "ui"]
    # 2º gateway (restart): NOVA sala (memória zerada) + mesmo store_root → recarrega a conversa
    ep2 = GroupEndpoint(_six_bot_room(), FakeGroupChannel(), store_root=str(tmp_path))
    roles = [r for r, _ in ep2.room.history]
    assert roles == ["USER", "cto", "ui"]                    # conversa do grupo sobreviveu ao restart
    assert ep2.room.turn > 0                                 # estado de turn-taking também


def test_telegram_group_channel_filters_own_bots(monkeypatch):
    from okami.channels.telegram import TelegramGroupChannel
    ch = TelegramGroupChannel({"cto": "tok1", "ui": "tok2"})
    ch._bot_ids = {111, 222}                                  # ids dos nossos bots
    updates = [
        {"update_id": 1, "message": {"chat": {"id": -100}, "from": {"id": 111, "is_bot": True}, "text": "eco do bot"}},
        {"update_id": 2, "message": {"chat": {"id": -100}, "from": {"id": 5, "is_bot": False}, "text": "oi humano"}},
        {"update_id": 3, "message": {"chat": {"id": -100}, "from": {"id": 9, "is_bot": True}, "text": "outro bot"}},
    ]
    monkeypatch.setattr(ch.listener, "get_updates", lambda offset=0, timeout=30: updates)
    got = ch.poll()
    assert [g.text for g in got] == ["oi humano"]            # anti-loop: só a fala humana passa


def test_feedback_evolves_persona_then_undo(tmp_path):
    from okami.learning import persona
    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch, run_task=_runner_ok,
                       spawn=lambda fn: fn())
    ep.handle("7", "/feedback seja mais conciso")                   # explícito → aplica na hora (auto)
    hist = persona.history(tmp_path)
    assert hist and hist[0]["text"] == "seja mais conciso"
    assert any("anotado" in t for _, t in ch.sent)
    ep.handle("7", "/undo")
    assert persona.history(tmp_path) == []                          # /undo reverteu


def test_observe_learns_user_style_gradually(tmp_path):
    from okami.learning import persona
    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch, run_task=_runner_ok,
                       spawn=lambda fn: fn())
    # palavrão é inferido (gradual): 1ª vez não pega; 2ª vez "pega" e evolui sozinho
    ep.handle("7", "porra, faz logo isso")
    assert persona.history(tmp_path) == []                          # ainda observando
    ep.handle("7", "caralho, ficou bom")
    voice = (tmp_path / "VOICE.md").read_text(encoding="utf-8")
    assert "palavrõ" in voice or "palavro" in voice                 # adaptou o tom sozinho
    assert "palavrões" in (tmp_path / "USER.md").read_text(encoding="utf-8")  # USER.md também
    assert not (tmp_path / "SOUL.md").exists()                      # SOUL nunca é tocado


def test_session_persists_across_restart(tmp_path):
    # 1º "gateway": conversa + /yolo → grava em disco
    ch1 = FakeChannel()
    ep1 = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch1, run_task=_runner_ok,
                        spawn=lambda fn: fn())
    ep1.handle("7", "primeira tarefa")
    ep1.handle("7", "/yolo")
    sess = tmp_path / ".okami" / "sessions"
    assert (sess / "sessions.json").exists() and (sess / "7.jsonl").exists()   # 2 camadas
    # 2º "gateway" (reinício): NOVA instância, mesma ws → recarrega a sessão
    ep2 = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=FakeChannel(), run_task=_runner_ok,
                        spawn=lambda fn: fn())
    s = ep2.session("7")
    assert len(s.history) >= 2 and s.yolo is True                   # contexto + estado sobreviveram ao restart


def _crashing_runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, emit=lambda m: None):
    raise RuntimeError("gateway caiu no meio")        # simula crash durante a tarefa


def test_interrupted_task_detected_and_retry(tmp_path):
    # tarefa que "crasha" → a msg do USER fica pendente (sem AGENTE) = interrompida
    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch, run_task=_crashing_runner,
                       spawn=lambda fn: fn())
    ep.handle("7", "tarefa importante")
    s = ep.session("7")
    assert s.interrupted() and s.history[-1] == ("USER", "tarefa importante")   # ficou pendente no disco
    # /retry com um runner OK conclui
    ep.run_task = _runner_ok
    ep.handle("7", "/retry")
    s2 = ep.session("7")
    assert not s2.interrupted() and s2.history[-1][0] == "AGENTE"


def test_auto_resume_on_boot_with_loop_guard(tmp_path):
    # 1º gateway: crash deixa interrompida
    AgentEndpoint("dev", None, str(tmp_path), FakeChannel(), run_task=_crashing_runner,
                  spawn=lambda fn: fn()).handle("7", "faz isso")
    # 2º gateway (restart) com auto_resume + runner que SEMPRE crasha → deve tentar 1x e DESISTIR (anti-loop)
    ch2 = FakeChannel()
    ep2 = AgentEndpoint("dev", None, str(tmp_path), ch2, run_task=_crashing_runner,
                        spawn=lambda fn: fn(), auto_resume=True)
    ep2.resume_interrupted(auto_resume=True, max_attempts=1)
    assert ep2.session("7").resume_attempts == 1                # tentou 1x
    # 3º restart: já bateu o teto → NÃO re-executa, só avisa (sem loop infinito — Hermes #7536)
    ch3 = FakeChannel()
    ep3 = AgentEndpoint("dev", None, str(tmp_path), ch3, run_task=_crashing_runner,
                        spawn=lambda fn: fn(), auto_resume=True)
    ep3.resume_interrupted(auto_resume=True, max_attempts=1)
    assert any("retry" in t.lower() for _, t in ch3.sent)        # avisou em vez de re-executar
    assert ep3.session("7").resume_attempts == 1                 # não passou do teto


def test_prune_sessions(tmp_path):
    ep = AgentEndpoint("dev", None, str(tmp_path), FakeChannel(), run_task=_runner_ok,
                       spawn=lambda fn: fn())
    for i in range(5):
        ep.handle(str(i), "oi")                                  # 5 sessões
    assert len(ep._all_session_ids()) == 5
    removed = ep.prune_sessions(max_sessions=2)                  # mantém só as 2 mais recentes
    assert removed == 3 and len(ep._all_session_ids()) == 2


def test_persona_session_overlay(tmp_path):
    captured = {}

    def runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, emit=lambda m: None, **kw):
        captured["ctx"] = extra_context
        return _ok_task(goal)

    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch, run_task=runner,
                       spawn=lambda fn: fn())
    ep.handle("7", "/persona conciso")
    assert ep.session("7").persona_overlay and "conciso" in ep.session("7").persona_overlay.lower()
    ep.handle("7", "faz a tarefa")
    assert "OVERLAY DE PERSONA" in captured["ctx"]               # overlay foi injetado no contexto
    ep.handle("7", "/persona off")                               # e some quando desligado
    assert ep.session("7").persona_overlay == ""


def test_build_group_endpoints_needs_member_token():
    from okami.gateway import build_group_endpoints
    specs = {
        "cto": AgentSpec("cto", Path("."), {"channels": {"telegram": {"token": "T1"}}, "role": "CTO"}),
        "ui": AgentSpec("ui", Path("."), {"role": "UI"}),    # sem token
    }
    graw = {"default_provider": "lmstudio", "providers": {"lmstudio": {"model": "openai/x", "api_key": "k"}}}
    msgs = []
    eps = build_group_endpoints(graw, specs, [{"members": ["cto", "ui"]}],
                                emit=msgs.append, make_channel=lambda tokens, **kw: FakeGroupChannel())
    assert len(eps) == 1                                     # grupo sobe com ≥1 token (cto)


def test_gateway_warns_on_unisolated_exposure(monkeypatch):
    from okami.core import sandbox as _sb
    from okami.gateway.builders import _warn_unisolated_exposure

    class _Ch:
        name = "telegram"

    class _Ep:
        channel = _Ch()
    msgs = []
    monkeypatch.setattr(_sb.shutil, "which", lambda *_: None)   # sem Docker
    # exposto + sem isolamento → avisa
    assert _warn_unisolated_exposure({}, [_Ep()], msgs.append) is True
    assert any("SEM ISOLAMENTO" in m for m in msgs) and any("okami harden" in m for m in msgs)
    # require_isolation: true → não avisa
    msgs2 = []
    assert _warn_unisolated_exposure({"sandbox": {"require_isolation": True}}, [_Ep()], msgs2.append) is False
    assert msgs2 == []


def test_harden_command_sets_require_isolation(tmp_path, monkeypatch):
    import yaml as _yaml
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")
    res = CliRunner().invoke(app, ["harden"])
    assert res.exit_code == 0
    local = _yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["sandbox"]["profile"] == "hardened-strict"          # postura nomeada (= o que o --strict aceita)
    # e o perfil de fato força isolamento em superfície exposta (runtime, não só o check)
    from okami.core.sandbox import effective_sandbox
    assert effective_sandbox(local["sandbox"], "telegram").backend == "docker"
    # --off remove o perfil (e não deixa sandbox vazio)
    CliRunner().invoke(app, ["harden", "--off"])
    local2 = _yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert (local2.get("sandbox") or {}).get("profile") != "hardened-strict"
