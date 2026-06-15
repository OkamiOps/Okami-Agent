"""provenance — verificação de proveniência por checksum (p/ binário baixado em runtime).

Antes de EXECUTAR um binário que o agente puxou da rede (ex.: ferramenta auxiliar), confere o
sha256 contra o esperado. `sha256_file` devolve 64 hex; `verify_checksum` compara case-insensitive
e é fail-safe — False em arquivo inexistente/hash diferente, nunca estoura no caller."""

from __future__ import annotations

from okami.core import provenance


def test_sha256_file_devolve_64_hex(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"okami")
    digest = provenance.sha256_file(f)
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_verify_checksum_hash_certo_true(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"conteudo conhecido")
    esperado = provenance.sha256_file(f)
    assert provenance.verify_checksum(f, esperado) is True


def test_verify_checksum_case_insensitive(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"conteudo conhecido")
    esperado = provenance.sha256_file(f).upper()           # esperado em MAIÚSCULAS
    assert provenance.verify_checksum(f, esperado) is True


def test_verify_checksum_hash_errado_false(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"conteudo conhecido")
    assert provenance.verify_checksum(f, "00" * 32) is False


def test_verify_checksum_arquivo_inexistente_false(tmp_path):
    ausente = tmp_path / "nao_existe"
    assert provenance.verify_checksum(ausente, "00" * 32) is False
