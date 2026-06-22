"""Bug sistêmico (caça e2e ampla): build_config montava OkamiConfig (pydantic extra=ignore) SEM os campos
integrations/media/computer_use → esses blocos do okami.yaml eram DESCARTADOS. Em runtime ctx.cfg é a
OkamiConfig, então x_search/homeassistant/feishu/generate_video/computer_use liam vazio e ficavam MORTAS
(podadas pra sempre, sem o dono conseguir ativar). A suíte mascarava: usava SimpleNamespace(integrations=)
em vez do cfg real. Mesmo padrão do [[okami-runner-harness-contract]]."""
from __future__ import annotations

from okami.config import build_config

_BASE = {"default_provider": "p", "providers": {"p": {"model": "m"}}}


def _cfg(**extra):
    return build_config({**_BASE, **extra})


def test_integrations_block_survives_build_config():
    cfg = _cfg(integrations={"x": {"api_key_env": "X_KEY"}})
    assert cfg.integrations == {"x": {"api_key_env": "X_KEY"}}   # antes: AttributeError/MISSING


def test_media_block_survives_build_config():
    cfg = _cfg(media={"video": {"backend": "fake", "url": "http://x"}})
    assert cfg.media == {"video": {"backend": "fake", "url": "http://x"}}


def test_computer_use_block_survives_build_config():
    cfg = _cfg(computer_use={"enabled": True})
    assert cfg.computer_use == {"enabled": True}


def test_x_search_config_actually_reaches_tool():
    from okami.integrations.x_search import x_config
    cfg = _cfg(integrations={"x": {"api_key_env": "X_KEY"}})
    assert x_config(cfg) is not None        # tool x_search deixa de nascer MORTA


def test_video_config_actually_reaches_tool():
    from okami.llm.videogen import video_config
    cfg = _cfg(media={"video": {"url": "http://x/gen", "model": "m"}})   # url direta (sem backend nomeado)
    assert video_config(cfg) is not None    # generate_video deixa de nascer MORTA


def test_missing_blocks_default_empty_not_error():
    cfg = _cfg()
    assert cfg.integrations == {} and cfg.media == {} and cfg.computer_use == {}
