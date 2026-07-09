"""Detector de NÃO-PROGRESSO por OUTPUT (paridade OpenClaw tool-loop-detection.ts).

O anti-loop do harness pega AÇÃO repetida (mesmos args). Falta o caso do OpenClaw: a tool roda, os
args mudam OU não, mas o RESULTADO é byte-a-byte o mesmo várias vezes seguidas — é I/O girando à toa
(poll de processo que não anda, read de arquivo que não muda). Aqui contamos repetição por OUTPUT,
por tool, resetando quando o resultado muda (= progresso de verdade)."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

_SIG_CAP = 4096        # hash só dos primeiros N chars (poll/estado muda no começo; barato e suficiente)


def output_signature(output: str) -> str:
    """Assinatura estável do output: normaliza espaços e capa o tamanho → mesma saída ⇒ mesma sig."""
    norm = " ".join((output or "").split())[:_SIG_CAP]
    return hashlib.blake2b(norm.encode("utf-8", "ignore"), digest_size=12).hexdigest()


class ProgressTracker:
    """Conta quantas vezes SEGUIDAS uma tool devolveu a MESMA saída. 0 = primeira vez (ou mudou)."""

    def __init__(self):
        self._last: dict[str, str] = {}     # tool → última assinatura de saída
        self._streak: dict[str, int] = {}   # tool → repetições consecutivas da MESMA saída

    def stalled_count(self, tool: str, output: str) -> int:
        sig = output_signature(output)
        if self._last.get(tool) == sig:
            self._streak[tool] = self._streak.get(tool, 0) + 1
        else:
            self._last[tool] = sig
            self._streak[tool] = 0
        return self._streak[tool]


# ------------------------------------------------------------------- cache idempotente (no-op skip)
# Paridade Hermes agent/tool_guardrails.py:298-319 (same_tool_failure_*/idempotent tracking): lá o
# guardrail CONTA repetições idênticas de uma tool read-only pra BLOQUEAR quando vira loop. Aqui vamos
# um passo além (ainda dentro do espírito idempotente): a MESMA tool read-only, com os MESMOS args,
# que já rodou este turno e devolveu um resultado de SUCESSO, não precisa rodar de novo — o resultado
# cacheado é devolvido na hora (com uma nota), poupando I/O redundante sem mudar o comportamento do
# agente (ele recebe o mesmo conteúdo que receberia rodando de novo).
#
# Escopo estreito de propósito:
#  - só tools READ-ONLY conhecidas (nunca uma tool que muta — write/edit/move/delete/run_shell/process_*
#    NUNCA entram aqui, mesmo que o chamador passe o nome errado: a allowlist é a defesa);
#  - só resultado de SUCESSO (`ok=True`) é cacheado — um erro nunca é servido do cache (mascarar erro
#    seria pior que re-rodar: o modelo precisa ver o erro de novo pra reagir, e o estado pode ter
#    mudado entre as chamadas);
#  - bounded (LRU pequena) — não é um cache de sessão, é só p/ o turno corrente não martelar a mesma
#    leitura repetida.
IDEMPOTENT_READONLY_TOOLS = frozenset({"read_file", "list_dir", "find_files", "search_files"})

_IDEMPOTENT_CACHE_MAX = 64   # LRU pequena — só cobre repetição dentro do MESMO turno, não histórico


def _args_key(args: dict | None) -> str:
    """Chave estável p/ um dict de args, independente da ORDEM de inserção (mesmos args, ordens
    diferentes → mesma chave)."""
    try:
        return json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        return repr(sorted((args or {}).items()))


class IdempotentCache:
    """Cache LRU bounded de resultados de tools READ-ONLY, por (tool, args). Só serve o cache quando
    tool está na allowlist IDEMPOTENT_READONLY_TOOLS e o resultado guardado foi um SUCESSO — nunca
    cacheia (nem serve) tool mutante ou resultado de erro."""

    def __init__(self, maxsize: int = _IDEMPOTENT_CACHE_MAX):
        self.maxsize = maxsize
        self._store: OrderedDict[tuple[str, str], object] = OrderedDict()  # (tool,argskey) -> ToolResult

    @staticmethod
    def is_cacheable_tool(tool: str) -> bool:
        return tool in IDEMPOTENT_READONLY_TOOLS

    def get(self, tool: str, args: dict | None):
        """Devolve o ToolResult cacheado p/ (tool,args) — ou None se não houver (ou tool não é
        elegível). NUNCA chame get() p/ tool mutante — a checagem `is_cacheable_tool` é responsabilidade
        do chamador (harness), aqui só reforçamos com o filtro de leitura."""
        if not self.is_cacheable_tool(tool):
            return None
        key = (tool, _args_key(args))
        if key in self._store:
            self._store.move_to_end(key)   # LRU: acesso recente sobe pro fim
            return self._store[key]
        return None

    def put(self, tool: str, args: dict | None, result) -> None:
        """Guarda `result` p/ (tool,args) — NO-OP se a tool não é read-only elegível ou se o resultado
        não foi sucesso (`result.ok` falsy). Erro NUNCA é cacheado (nunca deve mascarar um erro real)."""
        if not self.is_cacheable_tool(tool):
            return
        ok = getattr(result, "ok", False)
        if not ok:
            return
        key = (tool, _args_key(args))
        self._store[key] = result
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)   # evict o mais antigo (LRU)

    def served(self, tool: str, args: dict | None):
        """Como `get`, mas devolve uma CÓPIA do resultado cacheado com uma nota anexada ao output —
        deixa claro pro modelo (e pra quem lê o log) que esta chamada foi servida do cache, não
        re-executada, sem alterar o objeto guardado (chamadas futuras continuam batendo no mesmo
        resultado original)."""
        cached = self.get(tool, args)
        if cached is None:
            return None
        from dataclasses import replace
        note = "\n\n[cache: resultado idêntico já obtido nesta rodada — não re-executado]"
        try:
            return replace(cached, output=f"{cached.output}{note}")
        except TypeError:
            return cached

    def clear(self) -> None:
        """Zera o cache. O harness chama isto assim que QUALQUER tool com efeito (write/edit/shell/…) roda —
        senão um read_file cacheado serviria conteúdo OBSOLETO depois de o arquivo mudar (bug de correção)."""
        self._store.clear()
