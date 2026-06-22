"""Caça it.5 (segurança): hardline pega `rm -rf /$VAR`/`$()`; redact mascara chave TRUNCADA (sem END);
blackboard do swarm é atômico sob escrita concorrente."""
from __future__ import annotations

import threading


def test_hardline_blocks_var_expanded_rm_root():
    from okami.core.approval import detect_hardline as d
    assert d("bash -c 'rm -rf /$(echo home)'")   # cmd-sub colado na raiz (yolo-proof)
    assert d("rm -rf /$DIR")                       # var colada na raiz (vazia → rm -rf /)
    assert d("bash -c 'rm -rf /$HOME'")            # já pegava, segue pegando


def test_hardline_allows_legit_subpaths():
    from okami.core.approval import detect_hardline as d
    assert d("rm -rf /home/user/build") is None    # subpath de /home, não /home em si
    assert d("rm -rf ./build/$X") is None           # relativo, não raiz
    assert d("rm -rf /tmp/cache") is None


def test_redact_masks_truncated_private_key():
    from okami.core.redact import redact
    body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ" * 3      # corpo base64 longo, SEM END
    leaked = f"key=-----BEGIN RSA PRIVATE KEY-----\n{body}\n... (log cortado aqui)"  # pragma: allowlist secret
    out = redact(leaked)
    assert body not in out and "«redacted»" in out                       # corpo não vaza


def test_blackboard_append_atomic_under_concurrency(tmp_path):
    from okami.automation.swarm import blackboard_append, blackboard_read
    bb = tmp_path / "bb.jsonl"
    payload = {"x": "y" * 4000}                                            # >PIPE_BUF → append cru intercalaria

    def worker(i):
        blackboard_append(bb, f"w{i}", {**payload, "i": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = blackboard_read(bb)                                          # toda linha é JSON íntegro
    assert len(entries) == 12 and {e["author"] for e in entries} == {f"w{i}" for i in range(12)}
