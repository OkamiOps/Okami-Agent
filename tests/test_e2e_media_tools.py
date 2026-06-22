"""Bugs achados RODANDO as funções de feature (workflow e2e rodada 2). Tools de mídia/execução não
podem CRASHAR cru — devem devolver ToolResult/erro acionável. 4 fixes (2 aplicados pelos agentes do
workflow + 2 meus), todos com teste exercitando a API REAL."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------- A: TTS backend desconhecido → erro limpo
def test_tts_unknown_backend_returns_clean_error():
    from okami.core.tools.speak import TextToSpeech
    cfg = SimpleNamespace(voice={"tts": {"enabled": True, "backend": "BACKEND_QUE_NAO_EXISTE"}})
    ctx = SimpleNamespace(cfg=cfg, workspace=Path(tempfile.mkdtemp()))
    res = TextToSpeech().run({"text": "oi"}, ctx)
    assert res.ok is False and "mal configurado" in res.output    # antes: ValueError escapava do run()


# ---------------------------------------------------------------- B: generate_video com resp null → RuntimeError
def test_generate_video_rejects_null_resp(tmp_path):
    from okami.llm import videogen
    cfg = SimpleNamespace(media={"video": {"url": "https://x/video", "model": "m", "api_key_env": ""}})
    with pytest.raises(RuntimeError, match="inválida"):                # JSON `null` → resp=None
        videogen.generate_video(cfg, "lobo", str(tmp_path / "v.mp4"), _post=lambda *a, **k: None)


# ---------------------------------------------------------------- C: endpoint de vídeo morto → erro acionável
def test_videogen_default_post_dead_endpoint_actionable_error():
    from okami.llm.videogen import _default_post
    with pytest.raises(RuntimeError, match="inacessível"):            # porta morta → RuntimeError, não URLError cru
        _default_post("http://127.0.0.1:1/x", {}, {})


# ---------------------------------------------------------------- D: execute_code com stdout não-UTF8 → ok
def test_execute_code_handles_non_utf8_stdout():
    from okami.core.tools.execute_code import ExecuteCode
    ctx = SimpleNamespace(workspace=Path(tempfile.mkdtemp()), sandbox=SimpleNamespace(mode="workspace-write"))
    res = ExecuteCode().run(
        {"code": "import os; os.write(1, b'\\xff\\xfe\\x00bad'); print('depois')"}, ctx)
    assert res.ok is True and "depois" in res.output                 # antes: UnicodeDecodeError escapava
