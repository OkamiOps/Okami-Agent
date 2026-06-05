"""Suíte de REGRESSÃO (#12) — qualidade de memória/persona/skills com casos ROTULADOS + thresholds.

Não é unidade fina: é o "não pode piorar". Roda o harness `metrics.evaluate` sobre datasets rotulados
exigindo limiares, varre os invariantes críticos (esquecido não vaza, escopo não cruza), cobre a matriz
LOCAL de backend (sqlite-fts5 × holographic) e mede seleção de skill por intenção e o steering de persona.
Se a qualidade cair abaixo do limiar, o CI quebra.
"""

from __future__ import annotations

import yaml
import pytest

from okami import skills as skillmod
from okami.learning.compiler import compile_turn
from okami.memory import metrics
from okami.memory.base import MemoryItem
from okami.memory.holographic import HRREncoder
from okami.memory.sqlite_fts5 import SqliteFTS5Memory

# ----------------------------------------------------------------- datasets rotulados (memória)
_FACTS = [
    {"text": "o deploy do app usa vercel", "kind": "decision"},
    {"text": "o banco de dados e postgres", "kind": "decision"},
    {"text": "os testes rodam com pytest", "kind": "fact"},
    {"text": "o usuario prefere tema escuro", "kind": "preference", "scope": "global"},
    {"text": "uso typescript no frontend", "kind": "fact"},
]
_CASES = [
    {"query": "onde fazemos o deploy", "relevant": ["vercel"]},
    {"query": "qual o banco de dados", "relevant": ["postgres"]},
    {"query": "como rodar os testes", "relevant": ["pytest"]},
    {"query": "tema preferido do usuario", "relevant": ["tema escuro"], "scope": "global"},
]


def _seed(store):
    for f in _FACTS:
        store.write(MemoryItem(text=f["text"], kind=f["kind"], scope=f.get("scope", "workspace")))


@pytest.mark.parametrize("backend", ["sqlite", "holographic"])
def test_memory_retrieval_quality(tmp_path, backend):
    enc = HRREncoder() if backend == "holographic" else None
    store = SqliteFTS5Memory(tmp_path / f"{backend}.db", clock=lambda: 1000.0, embedder=enc)
    _seed(store)
    res = metrics.evaluate(store, _CASES, k=3)
    assert res["recall"] >= 0.75, res            # acha o relevante quase sempre
    assert res["precision_at_k"] >= 0.30, res
    assert res["mrr"] >= 0.5, res                 # relevante perto do topo
    assert res["scope_accuracy"] == 1.0, res      # escopo NUNCA erra


def test_forget_never_leaks(tmp_path):
    store = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)
    _seed(store)
    victim = store.recent(100)[0]
    store.forget_item(victim.id)
    assert metrics.integrity(store)["forget_success_rate"] == 1.0
    assert all(i.id != victim.id for i in store.recall(victim.text, 5))   # não volta via recall


def test_scope_isolation_between_projects(tmp_path):
    a = SqliteFTS5Memory(tmp_path / "a.db", clock=lambda: 1.0)
    b = SqliteFTS5Memory(tmp_path / "b.db", clock=lambda: 1.0)
    a.write(MemoryItem(text="projeto A usa rails no backend"))
    b.write(MemoryItem(text="projeto B usa django no backend"))
    assert not any("rails" in i.text for i in b.recall("framework backend", 5))   # A não vaza em B


def test_weak_inference_does_not_outrank_explicit(tmp_path):
    # 'não salva inferência fraca como fato forte': consolidação não rebaixa preferência explícita (high)
    store = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)
    store.write(MemoryItem(text="usuario prefere dark mode no editor sempre", kind="preference", confidence="high"))
    store.write(MemoryItem(text="usuario prefere dark mode no editor talvez", kind="preference", confidence="low"))
    assert store.consolidate()["merged"] == 0 and store.count() == 2


# ----------------------------------------------------------------- skills por intenção
_SKILLS = [
    {"name": "deploy-docker", "description": "subir container no docker",
     "triggers": ["faz deploy", "sobe o container"]},
    {"name": "analise-codigo", "description": "avaliar mudancas no projeto",
     "triggers": ["analisa o codigo", "ve se melhorou"]},
    {"name": "escrever-post", "description": "escrever post de blog",
     "triggers": ["escreve um texto", "post pro blog"]},
]
_SKILL_CASES = [
    ("amor, sobe o container de novo no docker", "deploy-docker"),
    ("da uma olhada se o codigo melhorou", "analise-codigo"),
    ("monta um textinho pro blog", "escrever-post"),
]


def test_skill_intent_selection_accuracy(tmp_path):
    for d in _SKILLS:
        sd = tmp_path / d["name"]
        sd.mkdir()
        (sd / "SKILL.md").write_text("---\n" + yaml.safe_dump(d, allow_unicode=True) + "---\ncorpo",
                                     encoding="utf-8")
    sks = skillmod.load_skills(tmp_path)
    hits = sum(1 for goal, exp in _SKILL_CASES if skillmod.rank_skills(goal, sks)[0][0].name == exp)
    assert hits / len(_SKILL_CASES) >= 0.66       # top-1 por INTENÇÃO (frase não-literal) ≥ 2/3


# ----------------------------------------------------------------- persona compiler (matriz)
def test_persona_steering_matrix():
    cases = [
        ("isso nao funciona de novo que saco", "frustrada"),
        ("urgente preciso disso pra ontem", "pressa"),
        ("como faco esse deploy do docker parar de quebrar", "técnico"),
        ("oi amor tudo bem saudades", ""),         # papo puro → sem bloco
    ]
    for goal, expect in cases:
        out = compile_turn(goal)
        if expect == "":
            assert out == "", goal
        else:
            assert expect in out.lower(), goal
