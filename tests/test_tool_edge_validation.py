"""Caça (loop it.1): robustez de tools a args malformados do MODELO FRACO (null/tipo errado) e a backends
que devolvem dict incompleto — antes alguns crashavam com AttributeError/KeyError em vez de erro LIMPO."""
from __future__ import annotations

from okami.core.tools.base import ToolContext


def _ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


def test_edit_file_null_path_clean_error(tmp_path):
    from okami.core.tools.files import EditFile
    res = EditFile().run({"path": None, "old": "x"}, _ctx(tmp_path))
    assert not res.ok and "path" in res.output and "string" in res.output    # erro limpo, não AttributeError


def test_process_write_null_id_clean_error(tmp_path):
    from okami.core.tools.process import ProcessWrite
    res = ProcessWrite().run({"id": None, "data": "oi"}, _ctx(tmp_path))
    assert not res.ok and "id" in res.output


def test_generate_image_null_prompt_clean_error(tmp_path):
    from okami.core.tools.agentic import GenerateImage
    res = GenerateImage().run({"prompt": None, "path": "x.png"}, _ctx(tmp_path))
    assert not res.ok and "prompt" in res.output


def test_websearch_tolerates_malformed_result(tmp_path, monkeypatch):
    import okami.integrations.web as web
    monkeypatch.setattr(web, "web_search", lambda q, limit: [{"title": "só título"}])   # sem url/snippet
    from okami.core.tools.websearch import WebSearch
    res = WebSearch().run({"query": "abc"}, _ctx(tmp_path))
    assert res.ok and "só título" in res.output and "sem url" in res.output             # não crashou


def test_apply_patch_rejects_reversed_markers():
    from okami.core.tools.patch import PatchError, parse_patch
    bad = "*** End Patch\n*** Begin Patch\n"
    import pytest
    with pytest.raises(PatchError):
        parse_patch(bad)                                                                # End antes de Begin → recusa


def test_sendmessage_reexported():
    from okami.core.tools import SendMessage                                            # paridade de export com Notify
    assert SendMessage is not None
