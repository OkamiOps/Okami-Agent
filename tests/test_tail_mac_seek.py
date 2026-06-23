"""Slowness (sweep #4): tail_mac lia o arquivo de auditoria INTEIRO só p/ pegar o mac da última linha — e é
chamado a CADA snapshot (rollback chama várias vezes → O(n²)). Refator p/ ler só a CAUDA via seek, SEM mudar
o resultado. Estes testes fixam o comportamento (inclusive o caminho de arquivo grande > 64KB)."""
from __future__ import annotations

import json

from okami.core.machain import tail_mac


def test_small_file_last_mac(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps({"mac": "x"}) + "\n" + json.dumps({"mac": "y"}) + "\n", encoding="utf-8")
    assert tail_mac(p) == "y"


def test_large_file_uses_tail_correctly(tmp_path):
    p = tmp_path / "audit.jsonl"
    lines = [json.dumps({"i": i, "mac": f"mac{i:05d}", "pad": "x" * 40}) for i in range(5000)]  # >64KB
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert tail_mac(p) == "mac04999"                      # último mac correto mesmo lendo só a cauda


def test_missing_and_empty(tmp_path):
    assert tail_mac(tmp_path / "nope.jsonl") == ""
    (tmp_path / "e.jsonl").write_text("", encoding="utf-8")
    assert tail_mac(tmp_path / "e.jsonl") == ""


def test_ignores_malformed_trailing_lines(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps({"mac": "good"}) + "\nLIXO NAO JSON\n\n", encoding="utf-8")
    assert tail_mac(p) == "good"
