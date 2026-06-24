"""Multi-vendor (Ollama/local — o dono usa/usará Ollama+LMStudio): Ollama default num_ctx=2048/4096 e TRUNCA
SILENCIOSO quando o prompt passa (system+tools do Okami estouram quase sempre) — o modelo "esquece" o início
sem erro. query_local_num_ctx descobre o teto real via /api/show; resolve_num_ctx cacheia e clampa <65K; o
request passa num_ctx pro Ollama alocar a janela certa."""
from __future__ import annotations

import json

from okami.config import ProviderConfig
from okami.llm.local_ctx import query_local_num_ctx, resolve_num_ctx


class _FakeResp:
    def __init__(self, payload): self._p = json.dumps(payload).encode()
    def read(self): return self._p
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_reads_num_ctx_from_parameters_string():
    def opener(req, timeout=None):
        return _FakeResp({"parameters": "num_ctx                 8192\nstop \"x\""})
    assert query_local_num_ctx("http://localhost:11434/v1", "qwen", _opener=opener) == 8192


def test_falls_back_to_model_info_context_length():
    def opener(req, timeout=None):
        return _FakeResp({"parameters": "", "model_info": {"llama.context_length": 32768}})
    assert query_local_num_ctx("http://localhost:11434", "llama3", _opener=opener) == 32768


def test_returns_none_on_error():
    def boom(req, timeout=None): raise OSError("connection refused")
    assert query_local_num_ctx("http://localhost:11434", "x", _opener=boom) is None
    assert query_local_num_ctx("", "x") is None


def test_resolve_caps_below_65k_and_caches():
    calls = {"n": 0}
    def q(api_base, model, **kw):
        calls["n"] += 1
        return 131072                                    # modelo enorme
    pc = ProviderConfig(name="ol", model="big", api_base="http://localhost:11434", tier="local")
    assert resolve_num_ctx(pc, "big", _query=q) == 65536     # clampa <65K
    assert resolve_num_ctx(pc, "big", _query=q) == 65536     # 2a vez NÃO re-consulta (cache)
    assert calls["n"] == 1


def test_kwargs_injects_num_ctx_for_local_not_cloud():
    from okami.llm import local_ctx, providers
    local_ctx._NUM_CTX_CACHE.clear()
    local_ctx._NUM_CTX_CACHE[("http://localhost:11434", "loc")] = 8192    # pré-semeia (sem rede)
    loc = ProviderConfig(name="ol", model="loc", api_base="http://localhost:11434", tier="local")
    kw = providers._kwargs(loc, [{"role": "user", "content": "oi"}], stream=False, model=None)
    assert kw.get("num_ctx") == 8192
    cloud = ProviderConfig(name="oai", model="gpt-4o", api_base="https://api.openai.com/v1")
    kw2 = providers._kwargs(cloud, [{"role": "user", "content": "oi"}], stream=False, model=None)
    assert "num_ctx" not in kw2                           # cloud não leva num_ctx
