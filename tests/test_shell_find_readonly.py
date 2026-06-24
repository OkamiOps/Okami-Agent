"""sandbox/shell (hunt#2): `find` puro (`find -name x`) era tratado como MUTANTE → bloqueado em read-only e
classificado como 'efeito' no watchdog. A INTENÇÃO era bloquear só `find -delete`/`find -exec rm`. Agora find
puro é read-only, mas as variantes destrutivas continuam pegas (pela 3ª alternativa do regex OU pelo token
destrutivo no -exec)."""
from __future__ import annotations

from okami.core.tools.base import shell_has_effect


def test_find_pure_is_readonly():
    assert shell_has_effect("find . -name '*.py' -type f") is False
    assert shell_has_effect("find src -type d") is False


def test_find_in_chain_is_readonly():
    assert shell_has_effect("cd src && find . -name x.py") is False


def test_find_delete_is_mutating():
    assert shell_has_effect("find . -name '*.tmp' -delete") is True


def test_find_exec_rm_is_mutating():
    assert shell_has_effect("find . -name '*.tmp' -exec rm {} ;") is True


def test_find_exec_other_destructive_still_caught():
    assert shell_has_effect("find . -exec mv {} /tmp ;") is True     # 'mv' (token genérico) pega


def test_plain_destructive_still_mutating():
    assert shell_has_effect("rm -rf build") is True
    assert shell_has_effect("grep -r foo .") is False
