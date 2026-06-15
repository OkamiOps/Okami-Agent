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


# --- janela de HORA (sufixo -1h): Nous/OpenRouter/OpenAI-compat mandam buckets x-ratelimit-*-1h ---

def test_parse_extrai_buckets_hora_1h():
    # além do minuto, o schema emite as 4 variantes de hora (requests-1h, tokens-1h)
    headers = {
        "x-ratelimit-limit-requests-1h": "1000",
        "x-ratelimit-remaining-requests-1h": "10",
        "x-ratelimit-reset-requests-1h": "2400",          # 40min em segundos
        "x-ratelimit-limit-tokens-1h": "2000000",
        "x-ratelimit-remaining-tokens-1h": "1500000",
        "x-ratelimit-reset-tokens-1h": "2400",
    }
    b = parse_rate_headers(headers)
    assert b["requests-1h"] == {"limit": 1000.0, "remaining": 10.0, "reset": "2400"}
    assert b["tokens-1h"] == {"limit": 2000000.0, "remaining": 1500000.0, "reset": "2400"}


def test_parse_minuto_e_hora_coexistem_sem_colidir():
    # minuto e hora juntos: cada header exato cai no seu bucket, sem um vazar pro outro
    headers = {
        "x-ratelimit-remaining-requests": "90",
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests-1h": "10",
        "x-ratelimit-limit-requests-1h": "1000",
    }
    b = parse_rate_headers(headers)
    assert b["requests"] == {"limit": 100.0, "remaining": 90.0}
    assert b["requests-1h"] == {"limit": 1000.0, "remaining": 10.0}


def test_parse_1h_e_case_insensitive():
    # provider varia o caixa até no sufixo (-1H) — lower() normaliza tudo
    b = parse_rate_headers({"X-RateLimit-Limit-Requests-1H": "1000",
                            "X-RateLimit-Remaining-Requests-1H": "5"})
    assert b["requests-1h"]["limit"] == 1000.0 and b["requests-1h"]["remaining"] == 5.0


def test_warning_considera_janela_hora_mesmo_com_minuto_folgado():
    # minuto folgado (90/100 = 10%) mas hora quase no teto (10/1000 = 99%) → avisa pela HORA
    headers = {
        "x-ratelimit-remaining-requests": "90",
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests-1h": "10",
        "x-ratelimit-limit-requests-1h": "1000",
        "x-ratelimit-reset-requests-1h": "2400",
    }
    w = usage_warning(parse_rate_headers(headers))
    assert w is not None
    assert "requests-1h" in w and "99%" in w and "2400" in w
