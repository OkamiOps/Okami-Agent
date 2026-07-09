"""Execução PARALELA de tools read-only do mesmo lote (pesquisa #7 item 20).

O loop já roda VÁRIAS leituras de uma geração em LOTE (Hermes multitool), mas serialmente — uma
após a outra. Quando o lote líder é todo read-only (read_file/list_dir/find_files/search_files,
run_shell sem efeito), elas são INDEPENDENTES: dá pra rodar em paralelo e cortar a latência (N reads
em ~1 read de wall-clock). Este módulo isola essa parte:

- `paths_collide(actions)`: por segurança, recusa o paralelo se duas ações tocam o MESMO subtree
  (defesa em profundidade — read-only não deveria colidir, mas se um write escapar p/ o lote o
  paralelo viraria corrida). Subtree-aware: `pkg/` colide com `pkg/mod.py`.
- `run_parallel(actions, registry, ctx, max_workers)`: ThreadPoolExecutor; resultados na ORDEM DE
  ENTRADA (determinístico p/ o loop emitir step/audit/observação em ordem); exceção de uma tool
  embrulhada em ToolResult(False, …) como o loop faz — uma falha NÃO derruba as outras. Tem um teto
  de RELÓGIO do LOTE (batch_timeout) — uma tool travada não segura o grupo até o watchdog do turno.

ADIADO (follow-up): tier write/patch em paralelo. Mutações + gate de aprovação ficam ESTRITAMENTE
seriais — paralelizar escrita exige um modelo de transação que não cabe aqui.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait as _futures_wait
from typing import Callable

from okami.core.harness.models import PARALLEL_BATCH_TIMEOUT_S
from okami.core.tools import ToolResult

# Intervalo-padrão de heartbeat (porte Hermes agent/tool_executor.py — "Heartbeat every ~30s"): sem
# isto, um lote longo (várias reads grandes, ou uma perto do teto de 420s) fica MUDO — gateway/UI não
# sabe se travou ou só está demorando. 30s casa com o Hermes.
HEARTBEAT_INTERVAL_S: float = 30.0


def _target_paths(action) -> list[str]:
    """Caminhos (relativos) que a ação TOCA — p/ detectar colisão de subtree. apply_patch usa
    patch_paths (multi-arquivo); o resto usa o arg `path`. Tool sem path → lista vazia (não colide)."""
    if action.tool == "apply_patch":
        from okami.core.tools.patch import patch_paths
        return patch_paths(str(action.args.get("patch", "")))
    p = action.args.get("path")
    return [str(p)] if isinstance(p, str) and p else []


def _norm(rel: str) -> str:
    """Normaliza um caminho relativo p/ comparação de subtree (sem resolver no FS — comparação textual
    estável). Tira ./ e barras duplicadas, padroniza separador."""
    parts = [seg for seg in str(rel).replace("\\", "/").split("/") if seg not in ("", ".")]
    return "/".join(parts)


def _subtree(a: str, b: str) -> bool:
    """`a` e `b` se sobrepõem na árvore? (igual, ou um é prefixo de diretório do outro)."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    return nb.startswith(na + "/") or na.startswith(nb + "/")


def paths_collide(actions: list) -> bool:
    """Alguma das ações toca o MESMO subtree de outra? True = NÃO é seguro paralelizar (serializa)."""
    paths = [(_norm(p)) for a in actions for p in _target_paths(a)]
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            if _subtree(paths[i], paths[j]):
                return True
    return False


def run_parallel(actions: list, registry: dict, ctx, max_workers: int = 8,
                 batch_timeout: float = PARALLEL_BATCH_TIMEOUT_S,
                 heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
                 on_heartbeat: Callable[[float, list[str]], None] | None = None) -> list[ToolResult]:
    """Roda as `actions` em paralelo (ThreadPool); devolve os ToolResult na ORDEM DE ENTRADA.

    Exceção de uma tool vira ToolResult(False, "erro na tool …") — exatamente como o loop embrulha,
    pra a falha de uma leitura não contaminar as outras nem derrubar o turno.

    `batch_timeout` (porte Hermes agent/tool_executor.py _resolve_concurrent_tool_timeout): teto de
    RELÓGIO do LOTE inteiro — sem isto, uma tool travada (run_shell sem saída, processo pendurado)
    segurava o grupo até o watchdog de 300s do TURNO (bem mais tardio, e derruba o turno inteiro em
    vez de só a tool travada). Estourou o teto → cada tool AINDA rodando vira ToolResult(False, …) de
    timeout; as que JÁ terminaram mantêm o resultado real. O worker travado fica ABANDONADO (thread
    daemon-like via shutdown(wait=False)) — mesma troca do Hermes: não trava o processo, mas a thread
    detached segue existindo até terminar sozinha.

    `on_heartbeat(elapsed_seconds, still_running_tools)` (porte Hermes _touch_activity a cada ~30s de
    lote concorrente): opcional — sem callback, nada muda (default None). Com callback, é chamado a
    cada `heartbeat_interval` segundos ENQUANTO o lote ainda tem tool pendente, pra o gateway/UI saber
    que o lote está vivo (não travado) em vez de ficar mudo até o timeout ou o fim do lote.
    Cancelamento gracioso: no timeout, futures ainda NA FILA (não iniciadas) são canceladas
    (`fut.cancel()`) — Python não preempta uma thread já rodando, então uma tool em andamento segue
    até terminar sozinha, mas o executor é abandonado (`shutdown(wait=False)`) em vez de bloquear o
    harness esperando por ela; nenhuma thread trava o processo."""
    if not actions:
        return []

    def _one(action) -> ToolResult:
        tool = registry.get(action.tool)
        if tool is None:                               # nome inválido escapou — não deveria, mas fail-open
            return ToolResult(False, f"erro na tool {action.tool}: não registrada")
        try:
            return tool.run(action.args, ctx)
        except Exception as e:  # noqa: BLE001 — uma tool NUNCA derruba o harness (espelha o loop)
            return ToolResult(False, f"erro na tool {action.tool}: {e}")

    workers = max(1, min(max_workers, len(actions)))
    ex = ThreadPoolExecutor(max_workers=workers)
    futures = [ex.submit(_one, action) for action in actions]

    # Espera em POLLS curtos (em vez de um único wait(batch_timeout)) — permite emitir heartbeat
    # periódico sem atrasar a detecção de "lote todo terminou" nem estourar o teto total.
    poll_s = min(heartbeat_interval, batch_timeout) if heartbeat_interval > 0 else batch_timeout
    poll_s = max(poll_s, 0.01)
    start = time.monotonic()
    last_heartbeat = start
    not_done: set = set(futures)
    while True:
        elapsed = time.monotonic() - start
        remaining = batch_timeout - elapsed
        if remaining <= 0:
            not_done = {f for f in futures if not f.done()}
            break
        _done, not_done = _futures_wait(futures, timeout=min(poll_s, remaining))
        if not not_done:
            break
        now = time.monotonic()
        if on_heartbeat is not None and (now - last_heartbeat) >= heartbeat_interval:
            last_heartbeat = now
            still = [action.tool for action, fut in zip(actions, futures) if fut in not_done]
            on_heartbeat(now - start, still)
    timed_out = bool(not_done)
    results: list[ToolResult] = []
    for action, fut in zip(actions, futures):
        if fut in not_done:
            fut.cancel()                                # no-op se já rodando (não cancela in-flight), mas
            results.append(ToolResult(False, f"erro na tool {action.tool}: timeout de lote "
                                      f"({batch_timeout:.0f}s) — ainda rodando quando o grupo estourou o "
                                      "teto; tente de novo isolada ou quebre em passos menores"))
        else:
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001 — mesma rede de segurança de _one, p/ erro no submit/future
                results.append(ToolResult(False, f"erro na tool {action.tool}: {e}"))
    # Sem estouro: shutdown normal (espera as threads terminarem, já terminaram mesmo). Com estouro:
    # NÃO espera as travadas (wait=False) — abandona-as detached em vez de travar o harness junto.
    ex.shutdown(wait=not timed_out, cancel_futures=timed_out)
    return results
