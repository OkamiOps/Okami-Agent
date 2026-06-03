"""Memória holográfica (HRR/VSA) — vetores gerados LOCALMENTE, sem servidor de embedding.

Holographic Reduced Representations (Plate): vetores aleatórios por token formam um codebook;
o texto vira a SUPERPOSIÇÃO (soma normalizada) dos vetores dos seus features (palavras +
trigramas de char, com accent-folding → robusto a morfologia/typos). Binding por convolução
circular (FFT) permite consultas composicionais (chave→valor) + cleanup.

Vantagem: dá relevância semântica-lexical SEM depender de um LLM/embedder remoto — ideal para
o cenário "sem máquina de embedding". Implementa a interface Embedder, então pluga direto no
backend rápido (SqliteFTS5Memory) reaproveitando BM25 + recência + importância + cosine vetorizado.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import numpy as np

from okami.memory.embeddings import Embedder

_WORD = re.compile(r"\w+", re.UNICODE)


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c))


def _trigrams(token: str) -> list[str]:
    t = f"#{token}#"
    return [t[i:i + 3] for i in range(len(t) - 2)] if len(t) >= 3 else [t]


class HRREncoder(Embedder):
    """Codebook HRR determinístico + encoding por superposição. Sem rede."""

    def __init__(self, dim: int = 1024):
        self.dim = dim
        self._cache: dict[str, np.ndarray] = {}

    def _atom(self, key: str) -> np.ndarray:
        v = self._cache.get(key)
        if v is None:
            seed = int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(), "big")
            v = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            self._cache[key] = v
        return v

    def _features(self, text: str) -> list[str]:
        feats: list[str] = []
        for w in _WORD.findall(text):
            fw = _fold(w)
            feats.append(f"w:{fw}")
            feats.extend(f"t:{g}" for g in _trigrams(fw))
        return feats

    def encode(self, text: str) -> np.ndarray:
        feats = self._features(text)
        if not feats:
            return np.zeros(self.dim, dtype=np.float32)
        v = np.sum([self._atom(f) for f in feats], axis=0)
        n = float(np.linalg.norm(v))
        return (v / n).astype(np.float32) if n > 0 else v

    # --- interface Embedder (pluga no SqliteFTS5Memory) ---
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t).tolist() for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.encode(text).tolist()

    # --- operações HRR composicionais (binding chave→valor) ---
    def bind(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.fft.irfft(np.fft.rfft(a) * np.fft.rfft(b), n=self.dim).astype(np.float32)

    def unbind(self, a: np.ndarray, c: np.ndarray) -> np.ndarray:
        # correlação circular = bind com o inverso aproximado (conjugado no domínio da frequência)
        return np.fft.irfft(np.conj(np.fft.rfft(a)) * np.fft.rfft(c), n=self.dim).astype(np.float32)

    def cleanup(self, noisy: np.ndarray, codebook: dict[str, np.ndarray]) -> str | None:
        """Item mais próximo do vetor ruidoso (recupera o símbolo 'limpo')."""
        best, best_sim = None, -1.0
        nn = float(np.linalg.norm(noisy)) or 1.0
        for name, vec in codebook.items():
            sim = float(np.dot(noisy, vec) / (nn * (np.linalg.norm(vec) or 1.0)))
            if sim > best_sim:
                best, best_sim = name, sim
        return best
