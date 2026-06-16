"""#18 geração de vídeo — provider configurável (degrada sem config), espelha o image-gen."""
from __future__ import annotations

from types import SimpleNamespace


def _cfg(media=None):
    return SimpleNamespace(media=media or {})


# ── config: lê media.video.* (None se não configurado) ──
def test_video_config_none_without_setup():
    from okami.llm.videogen import video_config
    assert video_config(_cfg()) is None
    assert video_config(_cfg({"video": {}})) is None       # sem url → não configurado


def test_video_config_reads_media_video():
    from okami.llm.videogen import video_config
    cfg = _cfg({"video": {"url": "https://api.fal.ai/v1/video", "model": "veo-3",
                          "api_key_env": "FAL_KEY", "poll_url": "https://api.fal.ai/v1/jobs"}})
    vc = video_config(cfg)
    assert vc["url"].endswith("/video") and vc["model"] == "veo-3" and vc["api_key_env"] == "FAL_KEY"


# ── geração SÍNCRONA (resposta já traz a URL do vídeo) ──
def test_generate_video_sync(tmp_path, monkeypatch):
    from okami.llm import videogen
    monkeypatch.setenv("FAL_KEY", "k")
    cfg = _cfg({"video": {"url": "https://x/video", "model": "veo-3", "api_key_env": "FAL_KEY"}})
    out = tmp_path / "v.mp4"
    posts = {}

    def _post(url, body, headers):
        posts["url"] = url
        posts["auth"] = headers.get("Authorization")
        return {"video": {"url": "https://x/result.mp4"}}

    def _download(url, dest):
        posts["dl"] = url
        dest.write_bytes(b"FAKEMP4")

    res = videogen.generate_video(cfg, "um lobo correndo", str(out), _post=_post, _download=_download,
                                  _validate=lambda u: None)
    assert res == str(out) and out.read_bytes() == b"FAKEMP4"
    assert posts["auth"] == "Bearer k" and posts["dl"] == "https://x/result.mp4"


def test_generate_video_blocks_ssrf_download_url(tmp_path, monkeypatch):
    # SEGURANÇA: a URL de download vem do PROVIDER (não-confiável) → passa pelo net_guard anti-SSRF
    import pytest

    from okami.llm import videogen
    monkeypatch.setenv("FAL_KEY", "k")
    cfg = _cfg({"video": {"url": "https://x/video", "model": "m", "api_key_env": "FAL_KEY"}})
    downloaded = {"hit": False}

    def _download(url, dest):
        downloaded["hit"] = True

    for evil in ("file:///etc/passwd", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(Exception):                     # noqa: B017 — BlockedURL (anti-SSRF)
            videogen.generate_video(cfg, "x", str(tmp_path / "v.mp4"),
                                    _post=lambda u, b, h: {"video": {"url": evil}}, _download=_download)
    assert downloaded["hit"] is False                      # NUNCA baixou o alvo malicioso


# ── geração ASSÍNCRONA (job id → poll até completar) ──
def test_generate_video_async_polls(tmp_path, monkeypatch):
    from okami.llm import videogen
    monkeypatch.setenv("FAL_KEY", "k")
    cfg = _cfg({"video": {"url": "https://x/video", "model": "veo-3", "api_key_env": "FAL_KEY",
                          "poll_url": "https://x/jobs"}})
    out = tmp_path / "v.mp4"
    states = iter([{"status": "running"}, {"status": "completed", "video": {"url": "https://x/done.mp4"}}])

    res = videogen.generate_video(
        cfg, "prompt", str(out),
        _post=lambda u, b, h: {"id": "job-1"},
        _get=lambda u, h: next(states),
        _download=lambda u, d: d.write_bytes(b"OK"),
        _sleep=lambda s: None, _validate=lambda u: None)
    assert res == str(out) and out.read_bytes() == b"OK"


def test_generate_video_without_config_raises(tmp_path):
    import pytest

    from okami.llm.videogen import generate_video
    with pytest.raises(RuntimeError, match="configure"):
        generate_video(_cfg(), "x", str(tmp_path / "v.mp4"))


def test_generate_video_without_key_raises(tmp_path, monkeypatch):
    import pytest

    from okami.llm.videogen import generate_video
    monkeypatch.delenv("FAL_KEY", raising=False)
    cfg = _cfg({"video": {"url": "https://x/video", "model": "m", "api_key_env": "FAL_KEY"}})
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        generate_video(cfg, "x", str(tmp_path / "v.mp4"), _post=lambda *a: {})


# ── tool generate_video ──
def test_generate_video_tool_registered():
    from okami.core.tools.registry import default_registry
    assert "generate_video" in default_registry()


def test_generate_video_tool_check_needs_config(tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.video import GenerateVideo
    ctx = ToolContext(workspace=tmp_path, cfg=_cfg())
    # sem config → run devolve erro claro (não crash)
    res = GenerateVideo().run({"prompt": "x", "path": "v.mp4"}, ctx)
    assert res.ok is False and "configure" in res.output.lower()
