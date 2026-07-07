"""WIN #1 (mirror.py wiring) + WIN #2b (pii.py wiring): a entrega PROATIVA de um job do
scheduler (okami.gateway.builders._execute_scheduled_job) deve:
  1. mandar o texto CRU pro chat do usuário (ep.channel.send);
  2. espelhar a MESMA entrega no transcript da sessão-alvo (ep._append_turn), papel AGENTE,
     marcada com a origem 'cron' — paridade Hermes (sem isso o agente não sabe que ele mesmo
     já mandou aquilo e repete/se contradiz no próximo turno);
  3. mascarar PII (telefone/id longo) no texto ESPELHADO (que volta pro contexto do LLM no
     próximo turno) SEM mascarar o texto que vai pro usuário.

Tudo hermético: fakes mínimos, sem thread/socket real (mesmo estilo de test_builders_wiring.py).
"""

from __future__ import annotations

from okami.gateway import builders


class FakeChannel:
    def __init__(self, name="telegram"):
        self.name = name
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))


class FakeSession:
    def __init__(self):
        self.history: list[tuple[str, str]] = []


class FakeTaskResult:
    def __init__(self, result):
        self.result = result
        self.reason = None
        self.state = None


class FakeEndpoint:
    """Endpoint mínimo p/ exercitar _execute_scheduled_job: run_task, channel, session, _append_turn."""

    def __init__(self, agent_id, ws, home="casa-1", channel_name="telegram", task_result="ok"):
        self.agent_id = agent_id
        self.ws = ws
        self.home = ws
        self.cfg = object()
        self.open_fs = True
        self.channel = FakeChannel(channel_name)
        self._home = home
        self._task_result = task_result
        self.sessions: dict[str, FakeSession] = {}
        self.appended: list[tuple[str, str, str]] = []   # (chat_id, role, text)

    def home_chat(self):
        return self._home

    def run_task(self, cfg, ws, prompt, **kw):
        return FakeTaskResult(self._task_result)

    def session(self, chat_id):
        return self.sessions.setdefault(str(chat_id), FakeSession())

    def _append_turn(self, chat_id, s, role, text):
        s.history.append((role, text))
        self.appended.append((str(chat_id), role, text))


def _run_one(ep, job: dict):
    from okami.automation.scheduler import Scheduler
    sched = Scheduler(str(ep.ws))
    by_agent = {ep.agent_id: ep}
    return builders._execute_scheduled_job(job, by_agent=by_agent, eps=[ep], sched=sched,
                                            toast=lambda t, b: None)


def test_delivery_is_mirrored_into_target_session(tmp_path):
    ep = FakeEndpoint("okami", str(tmp_path), home="casa-9", task_result="relatório pronto")
    job = {"id": "job1", "agent": "okami", "prompt": "faz o relatório", "target": None}

    text = _run_one(ep, job)

    assert text == "relatório pronto"
    # entregou ao usuário
    assert ep.channel.sent and ep.channel.sent[0][0] == "casa-9"
    assert "relatório pronto" in ep.channel.sent[0][1]
    # espelhou no transcript da MESMA sessão-alvo
    assert ep.appended, "entrega proativa não foi espelhada no transcript (WIN #1)"
    chat_id, role, mirrored = ep.appended[0]
    assert chat_id == "casa-9"
    assert role == "AGENTE"
    assert "cron" in mirrored                 # marca a origem — paridade Hermes
    assert "relatório pronto" in mirrored


def test_mirror_reaches_session_history(tmp_path):
    ep = FakeEndpoint("okami", str(tmp_path), home="casa-1", task_result="feito")
    job = {"id": "j2", "agent": "okami", "prompt": "x", "target": None}
    _run_one(ep, job)
    s = ep.sessions["casa-1"]
    assert s.history and s.history[0][0] == "AGENTE"


def test_silent_result_not_delivered_nor_mirrored(tmp_path):
    ep = FakeEndpoint("okami", str(tmp_path), home="casa-1", task_result="[SILENT]")
    job = {"id": "j3", "agent": "okami", "prompt": "x", "target": None}
    _run_one(ep, job)
    assert ep.channel.sent == []
    assert ep.appended == []                  # nada entregue → nada a espelhar


def test_pii_masked_in_mirror_but_not_in_outbound_message(tmp_path):
    """Telefone/id longo no resultado: o texto que vai pro CHAT fica cru, mas o que vira
    HISTÓRICO (contexto do próximo turno do LLM) é mascarado — telegram é plataforma PII-safe."""
    ep = FakeEndpoint("okami", str(tmp_path), home="55119999988", channel_name="telegram",
                      task_result="liga pro cliente +55 11 99999-8888 amanhã")
    job = {"id": "j4", "agent": "okami", "prompt": "x", "target": None}

    _run_one(ep, job)

    sent_text = ep.channel.sent[0][1]
    assert "99999-8888" in sent_text          # ao usuário: cru

    mirrored_text = ep.appended[0][2]
    assert "99999-8888" not in mirrored_text  # no espelho (prompt->LLM do próximo turno): mascarado
    assert "[telefone]" in mirrored_text


def test_pii_not_masked_on_unsafe_platform(tmp_path):
    """Discord precisa do id cru p/ montar menção — pii.redact_pii não mascara lá (fica fora de
    PII_SAFE_PLATFORMS); o espelho preserva o texto tal qual (fora o redact de segredo, que sempre roda)."""
    ep = FakeEndpoint("okami", str(tmp_path), home="chan-1", channel_name="discord",
                      task_result="liga pro cliente +55 11 99999-8888 amanhã")
    job = {"id": "j5", "agent": "okami", "prompt": "x", "target": None}

    _run_one(ep, job)

    mirrored_text = ep.appended[0][2]
    assert "99999-8888" in mirrored_text      # discord: cru também no espelho


def test_multi_target_mirrors_each_session(tmp_path):
    ep = FakeEndpoint("okami", str(tmp_path), home="casa-1", task_result="oi")
    job = {"id": "j6", "agent": "okami", "prompt": "x", "target": "111,222"}
    _run_one(ep, job)
    chat_ids = {c for c, _, _ in ep.appended}
    assert chat_ids == {"111", "222"}
