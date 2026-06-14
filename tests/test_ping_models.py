"""`_ping_models` expõe os ids do /models (3-tupla) p/ o doctor distinguir endpoint-off de typo.

A função já montava `ids` internamente e os jogava fora. Agora devolve `(ok, msg, ids)`, e é isso
que deixa `okami doctor` preencher `model_present` de verdade (build_report passa `_ping_models`)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from typer.testing import CliRunner

from okami.cli import app
from okami.cli._shared import _ping_models

runner = CliRunner()


class _FakeResp:
    """Resposta mínima compatível com `with urllib.request.urlopen(...) as r: r.read()`."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(payload: dict):
    def opener(url, timeout=None):
        return _FakeResp(payload)
    return opener


def test_ping_models_returns_three_tuple_with_ids(monkeypatch):
    payload = {"data": [{"id": "qwen3.5-9b-mtp"}, {"id": "other-model"}]}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(payload))
    res = _ping_models("http://localhost:1234/v1")
    assert len(res) == 3                                  # (ok, msg, ids)
    ok, msg, ids = res
    assert ok is True
    assert ids == ["qwen3.5-9b-mtp", "other-model"]       # ids brutos do /models, não descartados


def test_ping_models_error_path_has_empty_ids(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    res = _ping_models("http://localhost:1234/v1")
    assert len(res) == 3                                  # arity estável mesmo no erro
    ok, msg, ids = res
    assert ok is False
    assert ids == []                                      # sem endpoint → lista vazia, não None/ausente


def _write_cfg(tmp_path, model: str) -> None:
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\n"
        "providers:\n"
        f"  lmstudio: {{model: {model}, api_key: lm, tier: local, api_base: 'http://localhost:1234/v1'}}\n",
        encoding="utf-8")


def test_doctor_json_surfaces_model_present(tmp_path, monkeypatch):
    """Fluxo real: `okami doctor --json` → build_report(ping=_ping_models) → endpoint.model_present."""
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path, "openai/qwen3.5-9b-mtp")
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"data": [{"id": "qwen3.5-9b-mtp"}]}))
    res = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(res.output)
    ep = payload["providers"][0]["endpoint"]
    assert ep["ok"] is True
    assert ep["model_present"] is True                    # endpoint vivo + modelo presente


def test_doctor_json_model_present_false_on_typo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path, "openai/qwen3.5-9b-mtpX")        # typo: não está no /models
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"data": [{"id": "qwen3.5-9b-mtp"}]}))
    res = runner.invoke(app, ["doctor", "--json"])
    ep = json.loads(res.output)["providers"][0]["endpoint"]
    assert ep["ok"] is True
    assert ep["model_present"] is False                   # endpoint vivo, mas modelo não existe lá


def test_doctor_rich_path_tolerates_three_tuple(tmp_path, monkeypatch):
    """Regressão p/ basics.py:198 — o caminho rico (sem --json) também desempacota o ping; com a
    3-tupla ele PRECISA tolerar o 3º elemento, senão ValueError derruba o comando."""
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path, "openai/qwen3.5-9b-mtp")
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"data": [{"id": "qwen3.5-9b-mtp"}]}))
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0, res.output                 # não pode estourar ao desempacotar o ping
