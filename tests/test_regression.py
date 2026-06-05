"""Suíte de REGRESSÃO (#12) — qualidade de memória/persona/skills com casos ROTULADOS + thresholds.

Não é unidade fina: é o "não pode piorar". Roda o harness `metrics.evaluate` sobre datasets rotulados
exigindo limiares, varre os invariantes críticos (esquecido não vaza, escopo não cruza, relevância
vence recência), cobre a matriz LOCAL de backend (sqlite-fts5 × holographic) e mede seleção de skill
por intenção (inclusive ADVERSARIAL: nome parecido ≠ skill certa) e o steering de persona.
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

# ----------------------------------------------------------------- dataset rotulado (memória) ----------
# Cada query compartilha ≥1 palavra de conteúdo com o fato relevante (retrieval semântico-lexical).
_FACTS = [
    {"text": "o deploy do app usa vercel", "kind": "decision"},
    {"text": "o banco de dados e postgres", "kind": "decision"},
    {"text": "os testes rodam com pytest", "kind": "fact"},
    {"text": "a autenticacao usa oauth com google", "kind": "decision"},
    {"text": "o cache fica no redis", "kind": "decision"},
    {"text": "uso typescript no frontend", "kind": "fact"},
    {"text": "a api segue o padrao rest", "kind": "fact"},
    {"text": "os logs vao pro datadog", "kind": "fact"},
    {"text": "o usuario prefere tema escuro", "kind": "preference", "scope": "global"},
    {"text": "o usuario prefere mensagens curtas e diretas", "kind": "preference", "scope": "global"},
]
_CASES = [
    {"query": "onde fazemos o deploy", "relevant": ["vercel"]},
    {"query": "qual o banco de dados", "relevant": ["postgres"]},
    {"query": "como rodar os testes", "relevant": ["pytest"]},
    {"query": "como funciona a autenticacao", "relevant": ["oauth"]},
    {"query": "onde fica o cache", "relevant": ["redis"]},
    {"query": "qual a linguagem do frontend", "relevant": ["typescript"]},
    {"query": "qual padrao a api segue", "relevant": ["rest"]},
    {"query": "onde ficam os logs", "relevant": ["datadog"]},
    {"query": "qual o tema preferido", "relevant": ["tema escuro"], "scope": "global"},
    {"query": "como o usuario gosta das mensagens", "relevant": ["mensagens curtas"], "scope": "global"},
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
    assert res["recall"] >= 0.85, res            # acha o relevante quase sempre (10 casos)
    assert res["precision_at_k"] >= 0.30, res
    assert res["mrr"] >= 0.6, res                 # relevante perto do topo
    assert res["scope_accuracy"] == 1.0, res      # escopo NUNCA erra (2 casos rotulados)


@pytest.mark.parametrize("backend", ["sqlite", "holographic"])
def test_forget_never_leaks_any_backend(tmp_path, backend):
    enc = HRREncoder() if backend == "holographic" else None
    store = SqliteFTS5Memory(tmp_path / f"{backend}.db", clock=lambda: 1000.0, embedder=enc)
    _seed(store)
    victim = store.recall("deploy", 3)[0]
    store.forget_item(victim.id)
    assert metrics.integrity(store)["forget_success_rate"] == 1.0
    assert all(i.id != victim.id for i in store.recall(victim.text, 5))   # holographic/sqlite não retornam esquecido


def test_relevance_beats_recency(tmp_path):
    # 'não prioriza similaridade/recência sobre o relevante': fato ANTIGO mas relevante vence os recentes.
    store = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: 1000.0)
    store.write(MemoryItem(text="o pagamento usa stripe", kind="decision"))   # mais ANTIGO
    for i in range(6):
        store.write(MemoryItem(text=f"nota recente irrelevante numero {i}", kind="fact"))
    top = store.recall("qual gateway de pagamento", 3)
    assert top and "stripe" in top[0].text                                 # o antigo-relevante no topo


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


def test_expired_memory_not_retrieved(tmp_path):
    now = [1000.0]
    store = SqliteFTS5Memory(tmp_path / "m.db", clock=lambda: now[0])
    store.write(MemoryItem(text="tarefa temporaria do sprint atual", kind="fact", expires_at=1500.0))
    store.write(MemoryItem(text="decisao duravel sobre arquitetura", kind="decision"))
    now[0] = 2000.0
    assert not any("temporaria" in i.text for i in store.recall("tarefa sprint", 5))


# ----------------------------------------------------------------- skills por intenção (com adversarial)
_SKILLS = [
    {"name": "deploy-docker", "description": "subir container em producao",
     "triggers": ["faz deploy", "sobe o container", "poe em producao"]},
    {"name": "docker-logs", "description": "ver os logs de um container docker",
     "triggers": ["ver os logs do container", "olha o log do docker"]},
    {"name": "analise-codigo", "description": "avaliar mudancas no projeto depois de commit",
     "triggers": ["analisa o codigo", "ve se melhorou", "compara de novo"]},
    {"name": "escrever-post", "description": "escrever post de blog",
     "triggers": ["escreve um texto", "post pro blog"]},
    {"name": "rodar-testes", "description": "rodar a suite de testes e o lint",
     "triggers": ["roda os testes", "passa o lint"]},
]
_SKILL_CASES = [
    ("amor, sobe o container de novo no docker", "deploy-docker"),
    ("preciso por isso em producao", "deploy-docker"),
    ("da uma olhada se o codigo melhorou", "analise-codigo"),
    ("monta um textinho pro blog", "escrever-post"),
    ("passa a suite de testes ai", "rodar-testes"),
    # ADVERSARIAL: 'container docker' bate textualmente nas duas, mas a INTENÇÃO é VER LOG → docker-logs
    ("me mostra o log daquele container", "docker-logs"),
]


def _load_skills(tmp_path):
    for d in _SKILLS:
        sd = tmp_path / d["name"]
        sd.mkdir()
        (sd / "SKILL.md").write_text("---\n" + yaml.safe_dump(d, allow_unicode=True) + "---\ncorpo",
                                     encoding="utf-8")
    return skillmod.load_skills(tmp_path)


def test_skill_intent_selection_accuracy(tmp_path):
    sks = _load_skills(tmp_path)
    hits = sum(1 for goal, exp in _SKILL_CASES if skillmod.rank_skills(goal, sks)[0][0].name == exp)
    assert hits / len(_SKILL_CASES) >= 0.66, [(g, skillmod.rank_skills(g, sks)[0][0].name) for g, _ in _SKILL_CASES]


def test_skill_unrelated_goal_low_score(tmp_path):
    # goal sem relação com nenhuma skill → o topo NÃO deve ter score alto (não força skill errada)
    sks = _load_skills(tmp_path)
    ranked = skillmod.rank_skills("qual a capital da franca", sks)
    assert ranked[0][1] < 0.45                                 # nada casa forte → score baixo


# ----------------------------------------------------------------- persona compiler (matriz ampliada)
@pytest.mark.parametrize("goal,expect", [
    ("isso nao funciona de novo que saco", "frustrada"),
    ("ja tentei mil vezes e nao vai, travou tudo", "frustrada"),
    ("urgente preciso disso pra ontem", "pressa"),
    ("to com pressa, manda rapido", "pressa"),
    ("amei ficou incrivel, top demais", "animada"),
    ("como faco esse deploy do docker parar de quebrar", "técnico"),
    ("me ajuda a entender esse stacktrace do python", "técnico"),
    ("oi amor tudo bem, saudades de voce", ""),                # papo puro → bloco vazio
    ("conta como foi seu dia", ""),
])
def test_persona_steering_matrix(goal, expect):
    out = compile_turn(goal)
    if expect == "":
        assert out == "", goal
    else:
        assert expect in out.lower(), (goal, out)


def test_persona_work_mode_skips_register_but_keeps_emotion():
    # modo trabalho (critério verificável) → sem linha de registro; mas a emoção (frustração) ainda entra
    out = compile_turn("conserta o build que ta quebrado de novo, que saco",
                       exit_criteria=[{"type": "shell_ok", "cmd": "make"}])
    assert "frustrada" in out.lower() and "técnico" not in out.lower()
