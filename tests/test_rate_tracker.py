"""rate_tracker — parse PROATIVO dos headers x-ratelimit e aviso de uso perto do teto.

A dor: hoje só reagimos ao 429 (rate_guard, depois do estouro). O provider já manda quanto
sobrou em CADA resposta (x-ratelimit-remaining-*); ler isso deixa avisar ANTES de bater no muro.
"""
from __future__ import annotations

from okami.llm.rate_tracker import parse_rate_headers, usage_warning


def test_parse_extrai_buckets_requests_e_tokens():
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "1",
        "x-ratelimit-reset-requests": "30",
        "x-ratelimit-limit-tokens": "50000",
        "x-ratelimit-remaining-tokens": "49000",
        "x-ratelimit-reset-tokens": "12",
    }
    b = parse_rate_headers(headers)
    assert b["requests"] == {"limit": 100.0, "remaining": 1.0, "reset": "30"}
    assert b["tokens"] == {"limit": 50000.0, "remaining": 49000.0, "reset": "12"}


def test_parse_e_case_insensitive():
    b = parse_rate_headers({"X-RateLimit-Remaining-Requests": "5", "X-RateLimit-Limit-Requests": "100"})
    assert b["requests"]["remaining"] == 5.0 and b["requests"]["limit"] == 100.0


def test_parse_ignora_header_ausente_sem_crashar():
    b = parse_rate_headers({"content-type": "application/json"})    # nada de rate-limit
    assert b == {} or b["requests"] == {} and b["tokens"] == {}


def test_parse_nao_crasha_com_entrada_zoada():
    # None, dict vazio, valor não-numérico → best-effort, nunca levanta
    assert isinstance(parse_rate_headers(None), dict)
    assert isinstance(parse_rate_headers({}), dict)
    b = parse_rate_headers({"x-ratelimit-limit-requests": "abc"})   # lixo no lugar do número
    assert isinstance(b, dict)


def test_warning_dispara_perto_do_teto():
    # remaining=1 de 100 → uso 99% > 0.8 → aviso não-None mencionando requests e o reset
    b = parse_rate_headers({"x-ratelimit-remaining-requests": "1",
                            "x-ratelimit-limit-requests": "100",
                            "x-ratelimit-reset-requests": "30"})
    w = usage_warning(b)
    assert w is not None
    assert "requests" in w and "30" in w


def test_warning_none_quando_folgado():
    # remaining=90 de 100 → uso 10% < 0.8 → sem aviso
    b = parse_rate_headers({"x-ratelimit-remaining-requests": "90",
                            "x-ratelimit-limit-requests": "100"})
    assert usage_warning(b) is None


def test_warning_respeita_threshold_custom():
    b = parse_rate_headers({"x-ratelimit-remaining-requests": "70",
                            "x-ratelimit-limit-requests": "100"})   # uso 30%
    assert usage_warning(b, threshold=0.2) is not None              # threshold baixo → dispara
    assert usage_warning(b, threshold=0.5) is None                  # threshold alto → não


def test_warning_none_com_buckets_vazios_ou_invalidos():
    assert usage_warning({}) is None
    assert usage_warning(None) is None
    # limit=0 não pode virar divisão por zero
    assert usage_warning({"requests": {"limit": 0.0, "remaining": 0.0, "reset": None}}) is None


def test_usage_warning_opaque_reset_no_double_s():
    # achado da review #9: reset não-numérico (1m30s / timestamp) não vira "...ss".
    from okami.llm.rate_tracker import usage_warning
    w = usage_warning({"requests": {"limit": 100.0, "remaining": 1.0, "reset": "1m30s"}})
    assert w and "1m30ss" not in w and "1m30s" in w
