"""Flail de 49 passos (incidente do PDF): o circuit breaker chaveava o erro CRU, então cada workaround
(porta/PID/tmp diferente) gerava chave nova e o breaker de 3x NUNCA disparava. _norm_err normaliza →
variantes cosméticas do mesmo erro colidem."""
from okami.core.harness.loop import _norm_err


def test_variantes_cosmeticas_colidem():
    e = "puppeteer.launch() errno -88 at /tmp/{}/chrome on port {} (pid {})"
    k1 = _norm_err(e.format("xY3f9", 8931, 4211))
    k2 = _norm_err(e.format("zK9a1", 8932, 5122))
    k3 = _norm_err(e.format("qW2b7", 8933, 6033))
    assert k1 == k2 == k3            # os 3 workarounds colidem → breaker de 3x dispara


def test_erros_diferentes_nao_colidem():
    assert _norm_err("Permission denied /etc/passwd") != _norm_err("puppeteer errno -88 port 8931")


def test_breaker_dispara_com_variantes(monkeypatch):
    # simula o loop: 3 falhas cosmeticamente diferentes da MESMA abordagem → chave única → count chega a 3
    fails = {}
    for port in (8931, 8932, 8933):
        key = f"run_shell:{_norm_err(f'puppeteer errno -88 port {port} pid {port*2}')}"
        fails[key] = fails.get(key, 0) + 1
    assert len(fails) == 1 and max(fails.values()) == 3    # colidiram → breaker de 3x teria disparado
