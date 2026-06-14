"""machain — HMAC encadeado da trilha de auditoria (pesquisa #7 item 5).

Espelha a tamper-evidence dos checkpoints: cada linha do audit.jsonl leva um `mac` encadeado
(HMAC(key, prev_mac + payload)). 3 appends → verify True em tudo; chave 0600; adulterar uma
linha quebra ESSA e todas as SEGUINTES (a cadeia contamina o resto)."""

from __future__ import annotations

import json
import os
import stat

from okami.core import machain


def _read_entries(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_three_appends_verify_all_true(tmp_path):
    key = machain.key_for(tmp_path)
    audit = tmp_path / "audit.jsonl"
    prev = ""
    for i in range(3):
        payload = {"event": "tool", "step": i, "tool": "read_file"}
        mac = machain.mac(key, prev, payload)
        with audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**payload, "mac": mac}, ensure_ascii=False) + "\n")
        prev = mac
    ents = _read_entries(audit)
    assert machain.verify(key, ents) == [True, True, True]


def test_key_file_is_0600(tmp_path):
    machain.key_for(tmp_path)
    keyfile = tmp_path / ".okami" / ".audit_hmac.key"
    assert keyfile.exists()
    mode = stat.S_IMODE(os.stat(keyfile).st_mode)
    assert mode == 0o600


def test_key_is_stable_across_calls(tmp_path):
    assert machain.key_for(tmp_path) == machain.key_for(tmp_path)


def test_tamper_breaks_that_entry_and_following(tmp_path):
    key = machain.key_for(tmp_path)
    audit = tmp_path / "audit.jsonl"
    prev = ""
    for i in range(3):
        payload = {"event": "tool", "step": i}
        mac = machain.mac(key, prev, payload)
        with audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**payload, "mac": mac}, ensure_ascii=False) + "\n")
        prev = mac
    ents = _read_entries(audit)
    ents[1]["step"] = 999                              # adultera a 2ª entrada (payload muda, mac fica velho)
    oks = machain.verify(key, ents)
    assert oks[0] is True                              # antes do tamper: intacta
    assert oks[1] is False                             # a adulterada quebra
    assert oks[2] is False                             # e contamina a seguinte


def test_tail_mac_reads_last_mac(tmp_path):
    key = machain.key_for(tmp_path)
    audit = tmp_path / "audit.jsonl"
    assert machain.tail_mac(audit) == ""               # arquivo inexistente → ""
    prev = ""
    last = ""
    for i in range(2):
        payload = {"event": "tool", "step": i}
        last = machain.mac(key, prev, payload)
        with audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**payload, "mac": last}, ensure_ascii=False) + "\n")
        prev = last
    assert machain.tail_mac(audit) == last


# ----------------------------------------------------------------- integração com o Harness
def test_harness_audit_chains_and_verifies(tmp_path):
    """O _audit do harness grava campos FLAT + mac; a cadeia verifica de ponta a ponta."""
    import json as _json

    from okami.core import Harness, Task

    def J(tool, **args):
        return "```json\n" + _json.dumps({"tool": tool, "args": args}) + "\n```"

    class Script:
        def __init__(self, outs):
            self.outs = list(outs)

        def __call__(self, messages, schema=None):
            return self.outs.pop(0) if self.outs else J("respond", message="fim")

    Harness(Script([J("write_file", path="a.txt", content="oi"),
                    J("read_file", path="a.txt"),
                    J("respond", message="feito")]),
            Task(goal="cria e lê"), tmp_path, approve=lambda r: True).run()
    audit = tmp_path / ".okami" / "audit.jsonl"
    ents = _read_entries(audit)
    assert ents, "audit não gravou nada"
    assert all("mac" in e for e in ents)               # toda linha tem mac encadeado
    key = machain.key_for(tmp_path)
    assert all(machain.verify(key, ents))              # cadeia íntegra
    # campos FLAT preservados (leitores existentes do test_tools_sprint2 seguem funcionando)
    assert any(e.get("event") == "tool" and e.get("tool") == "write_file" for e in ents)
    assert all("ts" in e for e in ents)
