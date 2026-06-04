"""Backend de memória Honcho (Plastic Labs) — user-model + dialética, REMOTO.

Usa o SDK `honcho-ai`. `base_url` aponta para a instância (ex.: VPS dedicada via Tailscale),
então memória/agente/LLM ficam em hosts separados. Dep OPCIONAL: `pip install "okami-agent[honcho]"`.

Honcho é um ORÁCULO: `recall` usa a API dialética (`peer.chat`) e devolve um insight sintetizado
(não itens crus). `inject` traz a representação de contexto (user-model) para o system prompt.

NOTA: os nomes de método do SDK podem variar entre versões — o código é defensivo e você valida
contra a sua instância. `client` é injetável para teste.
"""

from __future__ import annotations

from okami.memory.base import Memory, MemoryItem


def _text_of(obj) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    for attr in ("content", "text", "message", "answer"):
        v = getattr(obj, attr, None)
        if isinstance(v, str):
            return v
    return str(obj)


class HonchoMemory(Memory):
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 workspace: str = "okami", user_peer: str = "user",
                 assistant_peer: str = "okami", session_id: str = "default", client=None):
        self._client = client or self._make_client(base_url, api_key, workspace)
        self.user = self._client.peer(user_peer)
        self.assistant = self._client.peer(assistant_peer)
        self.session = self._client.session(session_id)
        try:
            self.session.add_peers([self.user, self.assistant])
        except Exception:  # noqa: BLE001 — já adicionados / versão diferente
            pass

    @staticmethod
    def _make_client(base_url, api_key, workspace):
        try:
            from honcho import Honcho
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                'backend honcho requer o SDK: pip install "okami-agent[honcho]"'
            ) from e
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        if workspace:
            kwargs["workspace_id"] = workspace
        return Honcho(**kwargs)

    def write(self, item: MemoryItem) -> int:
        peer = self.assistant if item.source in ("agent", "task", "okami") else self.user
        try:
            self.session.add_messages([peer.message(item.text)])
        except Exception:  # noqa: BLE001
            pass
        return 0

    def _dialectic(self, query: str) -> str:
        for target in (self.assistant, self.user, self._client):
            chat = getattr(target, "chat", None)
            if callable(chat):
                try:
                    return _text_of(chat(query))
                except Exception:  # noqa: BLE001
                    continue
        return ""

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        text = self._dialectic(query)
        return [MemoryItem(text=text, kind="summary", source="honcho", score=1.0)] if text else []

    def inject(self, query: str = "", limit: int = 5) -> str:
        # Duas camadas (estilo Hermes): (1) contexto base do session.context() +
        # (2) dialética SEMPRE-ON no nível da PESSOA (não só da tarefa). É o que faz a resposta soar
        # ancorada em QUEM é a pessoa, não genérica. Cold start vs sessão em andamento usam queries
        # diferentes (strings do Hermes). Por cima, a dialética específica da tarefa (query).
        block = ""
        try:
            ctx = self.session.context()
            block = _text_of(ctx) if not hasattr(ctx, "to_prompt") else ctx.to_prompt()
        except Exception:  # noqa: BLE001
            block = ""
        cold = self.count() == 0
        person_q = ("Quem é essa pessoa? Quais as preferências, objetivos e jeito de trabalhar dela?"
                    if cold else
                    "Dado o que já foi conversado nesta sessão, que contexto sobre essa pessoa é o mais "
                    "relevante agora (nível técnico, tom que prefere, o que ela já decidiu)?")
        for q in (person_q, query):                  # pessoa primeiro; depois a tarefa
            if not q:
                continue
            hit = self._dialectic(q)
            if hit and hit not in block:
                block = (block + "\n" + hit).strip()
        # Header de USO (não rótulo passivo): convida o modelo a se ancorar sem recitar.
        return ("O que você já sabe dessa pessoa (use pra calibrar nível/tom e respeitar o que ela já "
                f"decidiu — não recite):\n{block}") if block else ""

    def recent(self, limit: int = 10) -> list[MemoryItem]:
        try:
            msgs = list(self.session.messages())
        except Exception:  # noqa: BLE001
            return []
        items = [MemoryItem(text=_text_of(m), kind="turn", source="honcho") for m in msgs[-limit:]]
        return list(reversed(items))

    def count(self) -> int:
        try:
            return len(list(self.session.messages()))
        except Exception:  # noqa: BLE001
            return 0
