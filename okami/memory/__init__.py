"""Memória plugável do Okami (§6)."""

from __future__ import annotations

import time
from pathlib import Path

from okami.memory import compaction, files
from okami.memory.base import Memory, MemoryItem
from okami.memory.embeddings import Embedder, OpenAICompatEmbedder
from okami.memory.sqlite_fts5 import SqliteFTS5Memory

__all__ = ["Memory", "MemoryItem", "SqliteFTS5Memory", "Embedder", "OpenAICompatEmbedder",
           "make_embedder", "open_memory", "compaction", "files"]


def make_embedder(cfg: dict | None) -> Embedder | None:
    """Constrói o embedder a partir de memory.embedder no okami.yaml (None = só keyword/BM25).

    Faz um probe rápido: se o endpoint (llama.cpp/Ollama/LMStudio) não responder, retorna None
    e a memória opera 100% sem embeddings. Use `probe: false` para pular o probe.
    """
    if not cfg or cfg.get("enabled") is False or not cfg.get("model"):
        return None
    emb = OpenAICompatEmbedder(
        api_base=cfg.get("api_base", "http://localhost:1234/v1"),
        model=cfg["model"],
        api_key=cfg.get("api_key", "-"),
    )
    if cfg.get("probe", True) and not emb.available():
        return None
    return emb


def open_memory(workspace: Path, backend="sqlite-fts5", clock=time.time,
                embedder: Embedder | None = None, config: dict | None = None) -> Memory:
    config = config or {}
    base = Path(workspace) / ".okami"
    base.mkdir(parents=True, exist_ok=True)

    # Camadas: backend pode ser uma lista (ex.: [holographic, honcho]) → LayeredMemory.
    # Tolerante: um backend que falha (honcho-ai ausente / VPS offline) é PULADO; os outros seguem.
    if isinstance(backend, (list, tuple)):
        import warnings

        from okami.memory.layered import LayeredMemory
        built, skipped = [], []
        for b in backend:
            try:
                built.append(open_memory(workspace, b, clock, embedder, config))
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{b}: {e}")
        if skipped:
            warnings.warn("memória — backends pulados → " + "; ".join(skipped), stacklevel=2)
        if not built:
            raise RuntimeError("nenhum backend de memória pôde ser inicializado: " + "; ".join(skipped))
        return LayeredMemory(built) if len(built) > 1 else built[0]

    name = str(backend).replace("-", "_").lower()

    if name in ("sqlite_fts5", "sqlite", "fts5", "default"):
        return SqliteFTS5Memory(base / "memory.db", clock=clock, embedder=embedder)

    if name in ("holographic", "hrr"):
        from okami.memory.holographic import HRREncoder
        dim = int((config.get("holographic") or {}).get("dim", 1024))
        # encoder HRR local faz o papel de "embedder" (sem rede) no backend rápido
        return SqliteFTS5Memory(base / "memory-holo.db", clock=clock, embedder=HRREncoder(dim))

    if name == "honcho":
        import os as _os

        from okami.core.envref import resolve_env
        from okami.memory.honcho_backend import HonchoMemory
        hc = config.get("honcho") or {}
        # api_key: literal (com ${ENV} resolvido) OU o valor da env nomeada em api_key_env.
        api_key = resolve_env(hc.get("api_key")) or _os.getenv(hc.get("api_key_env") or "") or None
        return HonchoMemory(
            base_url=resolve_env(hc.get("base_url")), api_key=api_key,
            workspace=hc.get("workspace_id") or hc.get("workspace") or "okami",   # workspace_id é o nome do SDK
            session_id=hc.get("session", "default"),
            user_peer=hc.get("user_peer", "user"), assistant_peer=hc.get("assistant_peer", "okami"),
        )

    raise ValueError(f"backend de memória desconhecido: {backend}")
