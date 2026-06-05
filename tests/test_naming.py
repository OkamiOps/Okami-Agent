"""core.naming.short_name — nomes CURTOS de tópico (skills auto-criadas + cron jobs)."""

from __future__ import annotations

from okami.core.naming import short_name


def test_drops_conversational_lead_in():
    # a frase literal do usuário NUNCA vira o nome
    assert short_name("agora vou pedir pra voce analisar seu codigo") == "analisar-codigo"
    assert short_name("legal eu queria que voce rodasse os testes") == "rodasse-testes"


def test_short_and_topic_focused():
    # ≤3 palavras, verbo genérico ('criar'/'gerar') descartado quando estoura → fica no substantivo
    assert short_name("cria um endpoint REST de pagamento com Stripe") == "endpoint-rest-pagamento"
    assert short_name("criar componente de login com shadcn") == "componente-login-shadcn"
    assert short_name("gerar relatorio de vendas mensal em pdf") == "relatorio-vendas-mensal"


def test_length_and_word_cap():
    for phrase in ["faz deploy do container no docker no kubernetes da aws",
                   "analisa a pasta inteira do projeto okami agent que esta aqui"]:
        n = short_name(phrase)
        assert len(n) <= 24 and n.count("-") <= 2          # no máx 3 palavras, ≤24 chars


def test_accents_stripped_and_kebab():
    n = short_name("configuração de produção")
    assert n == "configuracao-producao" and n.islower() and " " not in n


def test_keeps_short_tech_tokens():
    assert short_name("configurar pipeline ci") == "configurar-pipeline-ci"   # 'ci' preservado (não estoura)


def test_no_filler_leaks():
    for bad in ("agora", "voce", "pra", "eu", "vou", "pedir", "que", "por", "favor"):
        assert bad not in short_name("agora vou pedir pra voce por favor subir o flask").split("-")


def test_fallbacks():
    assert short_name("") == "item"
    assert short_name("", fallback="job") == "job"
    assert short_name("agora pode", tools=["run_shell", "run_shell"]) == "run-shell-task"
