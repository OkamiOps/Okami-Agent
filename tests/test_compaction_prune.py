"""Fase 1 da compactação (porta do pré-pass do Hermes): poda de OBSERVAÇÕES antigas SEM LLM.

Antes de dropar mensagens inteiras (perde contexto), os tool-results velhos viram 1 linha
informativa e saídas IDÊNTICAS repetidas são deduplicadas (reler o mesmo arquivo 5× mantinha
5 cópias no contexto). Barato, sem perda real — o transcript bruto segue na sessão.
"""
from __future__ import annotations

from okami.memory.compaction import estimate_chars, prune_observations


def _obs(step, tool, body, ok=True):
    return {"role": "user",
            "content": f"OBSERVAÇÃO (passo {step}, {tool} → {'ok' if ok else 'ERRO'}):\n{body}"}


def _hist(*msgs):
    return [{"role": "system", "content": "sys"}, *msgs]


def test_old_big_observation_becomes_one_liner():
    big = "x" * 5000
    msgs = _hist(_obs(1, "read_file", big),
                 {"role": "assistant", "content": "ok"},
                 *[{"role": "user", "content": f"m{i}"} for i in range(6)])
    out, saved = prune_observations(msgs, keep_tail=6)
    assert saved > 4000
    pruned = out[1]["content"]
    assert pruned.startswith("OBSERVAÇÃO (passo 1, read_file → ok)")   # cabeçalho preservado
    assert len(pruned) < 300
    assert "podado" in pruned and "chars saíram" in pruned             # diz o que saiu


def test_tail_observations_untouched():
    big = "y" * 5000
    msgs = _hist(*[{"role": "user", "content": f"m{i}"} for i in range(3)],
                 _obs(9, "run_shell", big))
    out, saved = prune_observations(msgs, keep_tail=4)
    assert saved == 0
    assert out[-1]["content"].endswith(big)                            # janela recente intocada


def test_identical_outputs_deduplicated():
    body = "conteúdo do arquivo\n" * 50
    msgs = _hist(_obs(1, "read_file", body),
                 {"role": "assistant", "content": "a"},
                 _obs(3, "read_file", body),                            # MESMA saída de novo
                 {"role": "assistant", "content": "b"},
                 *[{"role": "user", "content": f"m{i}"} for i in range(6)])
    out, saved = prune_observations(msgs, keep_tail=6)
    assert "idêntica" in out[1]["content"]                              # a ANTIGA vira ponteiro
    assert "passo 3" in out[1]["content"]
    assert len(out[3]["content"]) < len(f"OBSERVAÇÃO:\n{body}") + 100   # a recente vira 1-linha (fora do tail)


def test_small_and_non_observation_messages_untouched():
    msgs = _hist({"role": "user", "content": "pergunta normal do usuário"},
                 _obs(2, "list_dir", "a.txt\nb.txt"),                   # pequena: não vale podar
                 {"role": "assistant", "content": "resposta"},
                 *[{"role": "user", "content": f"m{i}"} for i in range(6)])
    out, saved = prune_observations(msgs, keep_tail=6)
    assert saved == 0
    assert out[1]["content"] == "pergunta normal do usuário"
    assert "a.txt" in out[2]["content"]


def test_estimate_drops_after_prune():
    msgs = _hist(*[_obs(i, "read_file", "z" * 3000) for i in range(8)],
                 *[{"role": "user", "content": f"m{i}"} for i in range(4)])
    before = estimate_chars(msgs)
    out, _ = prune_observations(msgs, keep_tail=4)
    assert estimate_chars(out) < before * 0.3
