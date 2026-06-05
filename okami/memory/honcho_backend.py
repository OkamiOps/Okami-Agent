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
                 assistant_peer: str = "okami", session_id: str = "default", client=None,
                 required: bool = False):
        self._failures = 0           # P2: saúde mínima — uma camada "importante" não pode morrer em silêncio
        self._last_error = ""
        self.required = required     # honcho.required: true → falha vira aviso ALTO (doctor/memory list)
        self._client = client or self._make_client(base_url, api_key, workspace)
        self.user = self._client.peer(user_peer)
        self.assistant = self._client.peer(assistant_peer)
        self.session = self._client.session(session_id)
        try:
            self.session.add_peers([self.user, self.assistant])
        except Exception as e:  # noqa: BLE001 — já adicionados / versão diferente
            self._fail(e)

    def _fail(self, e: Exception) -> None:
        self._failures += 1
        self._last_error = f"{type(e).__name__}: {e}"[:200]

    def health(self) -> dict:
        return {"backend": "honcho", "ok": self._failures == 0, "failures": self._failures,
                "last_error": self._last_error, "required": self.required}

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
        from okami.memory.base import is_secret_item
        if is_secret_item(item):                 # #P1: segredo não vai pro Honcho remoto (gate comum)
            return 0
        peer = self.assistant if item.source in ("agent", "task", "okami") else self.user
        try:
            self.session.add_messages([peer.message(item.text)])
        except Exception as e:  # noqa: BLE001
            self._fail(e)        # P2: registra a falha (Honcho morto não passa mais despercebido)
        return 0

    def _ask(self, peer, query: str, *, target=None) -> str:
        """peer.chat com os kwargs ideais, DEGRADANDO se a versão do SDK não suportar algum.

        `target` é o peer SOBRE QUEM perguntar. `assistant.chat(query, target=user)` = 'o que a Okami
        sabe sobre o usuário'; `user.chat(query)` = representação global do próprio usuário. NUNCA
        `assistant.chat(query)` sem target — isso perguntaria sobre a PRÓPRIA Okami (bug antigo)."""
        chat = getattr(peer, "chat", None)
        if not callable(chat):
            return ""
        if target is not None:
            # #P2: target FOI pedido → SÓ tentativas COM target. Se nenhuma colar (SDK antigo sem o
            # kwarg), retorna "" e o _dialectic cai p/ user.chat() — NUNCA chama assistant.chat(query)
            # sem target (isso voltaria a perguntar sobre a PRÓPRIA Okami = bug antigo).
            attempts = (dict(target=target, session=self.session, reasoning_level="low"),
                        dict(target=target, session=self.session), dict(target=target))
        else:
            attempts = (dict(session=self.session, reasoning_level="low"), dict(session=self.session), {})
        for kw in attempts:
            kw = {k: v for k, v in kw.items() if v is not None}
            try:
                return _text_of(chat(query, **kw))
            except TypeError:
                continue                                          # kwarg não suportado nessa versão → tenta menos
            except Exception as e:  # noqa: BLE001 — erro de runtime do SDK → desiste deste peer
                self._fail(e)
                return ""
        return ""

    def _dialectic(self, query: str) -> str:
        """O que a Okami sabe sobre o USUÁRIO (assistant.chat target=user); fallback: rep. global do user."""
        return self._ask(self.assistant, query, target=self.user) or self._ask(self.user, query)

    def _context(self, query: str = "") -> str:
        """Card/representação do USUÁRIO na perspectiva da Okami — session.context com peer_target.

        Sem peer_target a gente perdia o caminho mais forte (representação do user); degrada se o SDK
        não suportar os kwargs."""
        ctx_fn = getattr(self.session, "context", None)
        if not callable(ctx_fn):
            return ""
        ut, ap = getattr(self.user, "id", None), getattr(self.assistant, "id", None)
        for kw in (dict(peer_target=ut, peer_perspective=ap, search_query=query or None),
                   dict(peer_target=ut, peer_perspective=ap),
                   dict(peer_target=ut), {}):
            kw = {k: v for k, v in kw.items() if v is not None}
            try:
                ctx = ctx_fn(**kw)
                return ctx.to_prompt() if hasattr(ctx, "to_prompt") else _text_of(ctx)
            except TypeError:
                continue
            except Exception as e:  # noqa: BLE001
                self._fail(e)
                return ""
        return ""

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        text = self._dialectic(query)
        return [MemoryItem(text=text, kind="summary", source="honcho", score=1.0)] if text else []

    def inject(self, query: str = "", limit: int = 5) -> str:
        # Duas camadas (estilo Hermes): (1) contexto base do session.context() +
        # (2) dialética SEMPRE-ON no nível da PESSOA (não só da tarefa). É o que faz a resposta soar
        # ancorada em QUEM é a pessoa, não genérica. Cold start vs sessão em andamento usam queries
        # diferentes (strings do Hermes). Por cima, a dialética específica da tarefa (query).
        block = self._context(query)
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
        except Exception as e:  # noqa: BLE001
            self._fail(e)
            return []
        items = [MemoryItem(text=_text_of(m), kind="turn", source="honcho") for m in msgs[-limit:]]
        return list(reversed(items))

    def count(self) -> int:
        try:
            return len(list(self.session.messages()))
        except Exception as e:  # noqa: BLE001
            self._fail(e)
            return 0
