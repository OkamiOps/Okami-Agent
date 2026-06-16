"""#14: auto-install do binário tirith (download de release + verificação SHA-256, opt-in).

Diferença do Hermes: opt-in (não baixa binário sem o dono pedir), SHA-256 obrigatório, cosign opcional.
Download/extract injetáveis p/ testar sem rede."""
from __future__ import annotations

import hashlib


def test_sha256_hex():
    from okami.core.tirith import _sha256
    assert _sha256(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_platform_asset_name():
    from okami.core.tirith import _platform_asset
    osn, arch, asset = _platform_asset()
    assert osn in ("linux", "darwin", "windows") and asset.startswith("tirith")


def test_install_verifies_checksum(tmp_path):
    from okami.core.tirith import install_tirith
    payload = b"FAKE-TIRITH-BINARY"
    good_sha = hashlib.sha256(payload).hexdigest()
    fetched = {}

    def _fetch(url):
        fetched[url] = True
        if url.endswith("checksums.txt"):
            return f"{good_sha}  tirith_test.tar.gz\n".encode()
        return payload

    extracted = {}

    def _extract(data, dest):
        extracted["data"] = data
        return str(dest / "tirith")

    path = install_tirith(version="v1.0.0", dest=tmp_path, asset_name="tirith_test.tar.gz",
                          _fetch=_fetch, _extract=_extract)
    assert path and extracted["data"] == payload          # sha bateu → extraiu


def test_install_refuses_bad_checksum(tmp_path):
    from okami.core.tirith import install_tirith

    def _fetch(url):
        if url.endswith("checksums.txt"):
            return b"deadbeef  tirith_test.tar.gz\n"      # sha que NÃO bate
        return b"FAKE-TIRITH-BINARY"

    path = install_tirith(version="v1.0.0", dest=tmp_path, asset_name="tirith_test.tar.gz",
                          _fetch=_fetch, _extract=lambda d, p: "x")
    assert path is None                                    # checksum errado → recusa


def test_ensure_tirith_binary_disabled_noop():
    from okami.core.tirith import ensure_tirith_binary
    # auto_install desligado (default) → não instala, devolve None
    assert ensure_tirith_binary(cfg={"security": {"tirith_auto_install": False}}, _install=lambda **k: "x") is None


def test_ensure_tirith_binary_skips_when_present():
    from okami.core.tirith import ensure_tirith_binary
    installed = {"n": 0}
    ensure_tirith_binary(cfg={"security": {"tirith_auto_install": True}},
                         _which=lambda _n: "/usr/bin/tirith",   # já está no PATH
                         _install=lambda **k: installed.__setitem__("n", 1))
    assert installed["n"] == 0                             # já presente → não baixa
