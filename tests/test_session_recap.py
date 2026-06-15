"""Testes do recap de sessão SEM LLM (instantâneo) — okami.core.session_recap.

Cobre: contagem de turnos (pares user/agent), top ferramentas com contagem ("read_file×2"),
arquivos tocados (extraídos de args.path/src/dst), último pedido/resposta truncados, e fail-safe
(history vazio, steps None, step torto → nunca levanta)."""

from __future__ import annotations

from types import SimpleNamespace

from okami.core.session_recap import build_recap


def _step(tool, **args):
    """Step "fake" no formato esperado pelo build_recap (objeto com .tool e .args dict)."""
    return SimpleNamespace(tool=tool, args=args)


def test_recap_basico_turnos_ferramentas_arquivos_resposta():
    history = [
        ("USER", "abra o arquivo a.py e rode os testes"),
        ("AGENT", "li o a.py"),
        ("USER", "agora veja o b.py"),
        ("AGENT", "pronto, b.py inspecionado e tudo verde"),
    ]
    steps = [
        _step("read_file", path="a.py"),
        _step("read_file", path="b.py"),
        _step("run_shell", cmd="ls"),
    ]
    recap = build_recap(history, steps)

    assert isinstance(recap, str) and recap
    # 2 pares user/agent = 2 turnos
    assert "2" in recap
    # ferramenta mais usada com a contagem
    assert "read_file" in recap
    assert "read_file×2" in recap
    assert "run_shell" in recap
    # arquivo tocado, extraído de args.path
    assert "a.py" in recap
    assert "b.py" in recap
    # última resposta do agente aparece (ou parte dela)
    assert "b.py inspecionado" in recap


def test_recap_extrai_src_e_dst():
    history = [("USER", "mova o arquivo"), ("AGENT", "movido")]
    steps = [_step("move_file", src="velho.txt", dst="novo.txt")]
    recap = build_recap(history, steps)
    assert "velho.txt" in recap
    assert "novo.txt" in recap


def test_recap_trunca_textos_longos():
    longo = "x" * 500
    history = [("USER", longo), ("AGENT", longo)]
    recap = build_recap(history)
    # nenhum bloco de 500 chars sobrevive — truncado em ~120
    assert ("x" * 200) not in recap


def test_recap_failsafe_vazio_e_steps_none():
    # history vazio + steps None: não levanta, devolve str
    assert isinstance(build_recap([], None), str)
    assert isinstance(build_recap([]), str)


def test_recap_failsafe_steps_tortos():
    # steps com objeto sem .args / com args não-dict / None no meio: best-effort, sem explodir
    history = [("USER", "oi"), ("AGENT", "olá")]
    steps = [
        SimpleNamespace(tool="read_file", args=None),
        SimpleNamespace(tool=None, args={"path": "z.py"}),
        None,
        _step("run_shell", cmd="pwd"),
    ]
    recap = build_recap(history, steps)
    assert isinstance(recap, str) and recap
    assert "run_shell" in recap
