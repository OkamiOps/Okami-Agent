"""file_safety: jail de workspace, symlink-escape, teto de tamanho e escrita atômica."""

from __future__ import annotations

import os

import pytest

from okami.core.file_safety import (
    FileTooLarge, PathEscape, read_text_capped, safe_path, write_text_atomic,
)


def test_safe_path_jails_traversal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert safe_path(ws, "a/b.txt") == (ws / "a/b.txt").resolve()
    with pytest.raises(PathEscape):
        safe_path(ws, "../escapa.txt")
    with pytest.raises(PathEscape):
        safe_path(ws, "/etc/passwd")


def test_safe_path_blocks_symlink_escape(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    secret = tmp_path / "secret"        # FORA do workspace
    secret.mkdir()
    (secret / "k.txt").write_text("segredo", encoding="utf-8")
    link = ws / "link"
    try:
        os.symlink(secret, link)        # link dentro do ws aponta p/ fora
    except (OSError, NotImplementedError):
        pytest.skip("sem symlink neste ambiente")
    with pytest.raises(PathEscape):     # resolve() segue o link → cai fora do jail
        safe_path(ws, "link/k.txt")


def test_read_cap(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 100, encoding="utf-8")
    assert read_text_capped(p, limit=1000) == "x" * 100
    with pytest.raises(FileTooLarge):
        read_text_capped(p, limit=10)


def test_write_atomic_and_cap(tmp_path):
    p = tmp_path / "sub" / "out.txt"     # cria o diretório-pai sozinho
    n = write_text_atomic(p, "olá\nmundo")
    assert p.read_text(encoding="utf-8") == "olá\nmundo" and n == len("olá\nmundo")
    assert not list(p.parent.glob(".*tmp*"))      # sem tmp deixado pra trás
    with pytest.raises(FileTooLarge):
        write_text_atomic(p, "y" * 50, limit=10)
    assert p.read_text(encoding="utf-8") == "olá\nmundo"   # falha NÃO corrompeu o original
