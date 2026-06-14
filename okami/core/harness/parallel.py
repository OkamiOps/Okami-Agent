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
  embrulhada em ToolResult(False, …) como o loop faz — uma falha NÃO derruba as outras.

ADIADO (follow-up): tier write/patch em paralelo. Mutações + gate de aprovação ficam ESTRITAMENTE
seriais — paralelizar escrita exige um modelo de transação que não cabe aqui.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from okami.core.tools import ToolResult


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


def run_parallel(actions: list, registry: dict, ctx, max_workers: int = 8) -> list[ToolResult]:
    """Roda as `actions` em paralelo (ThreadPool); devolve os ToolResult na ORDEM DE ENTRADA.

    Exceção de uma tool vira ToolResult(False, "erro na tool …") — exatamente como o loop embrulha,
    pra a falha de uma leitura não contaminar as outras nem derrubar o turno."""
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
    with ThreadPoolExecutor(max_workers=workers) as ex:
        # executor.map preserva a ORDEM DE ENTRADA dos resultados (≠ as_completed) — determinístico.
        return list(ex.map(_one, actions))
