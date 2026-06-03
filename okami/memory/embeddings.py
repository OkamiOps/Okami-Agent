"""Embeddings para memória semântica (§6) — OPCIONAIS.

Embedder genérico p/ qualquer endpoint OpenAI-compatível: **llama.cpp** (`llama-server
--embeddings`), **Ollama**, **LMStudio**, ou um provider de API. Se ausente/offline, a memória
degrada para BM25 (keyword) + recência + importância — nunca depende de rodar embeddings.

Circuit breaker: na 1ª falha o embedder se DESABILITA (não fica martelando a rede).
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np


def cosine(a, b) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes):
    return np.frombuffer(blob, dtype=np.float32)


class Embedder:
    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - interface
        raise NotImplementedError

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAICompatEmbedder(Embedder):
    """Funciona com llama.cpp/Ollama/LMStudio/qualquer endpoint `/v1/embeddings`."""

    def __init__(self, api_base: str, model: str, api_key: str = "-", timeout: float = 20.0):
        self.base = api_base.rstrip("/")
        self.url = self.base + "/embeddings"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._disabled = False

    def available(self) -> bool:
        """Probe rápido (GET /models, 3s). Usado para decidir se vale ativar o embedder."""
        try:
            req = urllib.request.Request(self.base + "/models")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310
                return 200 <= getattr(r, "status", 200) < 300
        except Exception:  # noqa: BLE001
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._disabled:
            raise RuntimeError("embedder desabilitado (falha anterior)")
        try:
            body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
            req = urllib.request.Request(self.url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
            return [d["embedding"] for d in data["data"]]
        except Exception:  # noqa: BLE001 — circuit breaker
            self._disabled = True
            raise


# Compat: nome antigo.
LMStudioEmbedder = OpenAICompatEmbedder
