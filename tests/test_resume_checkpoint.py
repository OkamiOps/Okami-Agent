"""Crash-resume: checkpoint estruturado sobrevive a crash mid-tool-loop; resume semeia daqui (passos
feitos preservados) em vez de reconstruir [system,user]. Tail órfão (tool_call sem resultado) reparado."""
import tempfile, shutil
from pathlib import Path
from okami.core.harness.resume import write_checkpoint, load_checkpoint, clear_checkpoint


def _ws():
    return Path(tempfile.mkdtemp())


def test_fresco_carrega_velho_nao():
    ws = _ws()
    try:
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                {"role": "assistant", "content": "a"}]
        write_checkpoint(ws, msgs, ts=1000.0)
        assert load_checkpoint(ws, max_age_s=3600, now=1500.0) is not None      # 500s < 1h → fresco
        assert load_checkpoint(ws, max_age_s=3600, now=1000.0 + 7200) is None   # 2h → velho, não ressuscita
    finally:
        shutil.rmtree(ws)


def test_repara_tail_orfao():
    ws = _ws()
    try:
        # crash NO MEIO de uma tool: assistant declarou tool_call, nunca veio o role=tool
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                 "function": {"name": "read_file", "arguments": "{}"}}]}]
        write_checkpoint(ws, msgs, ts=1000.0)
        out = load_checkpoint(ws, max_age_s=3600, now=1100.0)
        assert out is not None
        # o par órfão foi consertado: existe um role=tool respondendo c1 (senão o rail nativo leva 400)
        assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in out)
    finally:
        shutil.rmtree(ws)


def test_ausente_ou_invalido_none():
    ws = _ws()
    try:
        assert load_checkpoint(ws, max_age_s=3600, now=1.0) is None            # sem arquivo → None (comportamento antigo)
        write_checkpoint(ws, [{"role": "system", "content": "só isso"}], ts=1.0)
        assert load_checkpoint(ws, max_age_s=3600, now=2.0) is None            # <2 msgs → inválido
    finally:
        shutil.rmtree(ws)


def test_clear_remove():
    ws = _ws()
    try:
        write_checkpoint(ws, [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], ts=1.0)
        clear_checkpoint(ws)
        assert load_checkpoint(ws, max_age_s=3600, now=2.0) is None
    finally:
        shutil.rmtree(ws)
