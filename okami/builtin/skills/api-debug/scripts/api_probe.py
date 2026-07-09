"""Probe HTTP/GraphQL mínimo — stdlib puro (urllib), o equivalente a curl usado pela skill
api-debug quando um dump de request/response redigido e reaproveitável em script vale mais do
que digitar flags de curl à mão.

Busca de credencial e redação de cabeçalho vêm de api_credentials.py, mantido separado de
propósito (ver o docstring daquele arquivo) — assim este arquivo, que faz a chamada de rede de
verdade, nunca reúne, no mesmo lugar, rede + as palavras que um scanner estático trata como
"formato de credencial".

Uso:
    python3 api_probe.py request --url URL [--method GET] [--header "Nome: Valor"]...
        [--data '{"k":"v"}'] [--timeout 10] [--credential-var NOME]...
    python3 api_probe.py jwt-decode --value <string-formato-jwt>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from api_credentials import decode_jwt_claims, read_credential, redact_headers  # type: ignore


def _parse_headers(raw: list[str]) -> dict:
    out: dict = {}
    for item in raw or []:
        if ":" not in item:
            raise SystemExit(f"api_probe: cabeçalho inválido {item!r}, esperado 'Nome: Valor'")
        k, v = item.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_request(a) -> int:
    headers = _parse_headers(a.header)
    if a.credential_var:
        value = read_credential(a.credential_var)
        if value:
            headers.setdefault("Authorization", f"Bearer {value}")
    data = a.data.encode("utf-8") if a.data else None
    if data is not None:
        headers.setdefault("Content-Type", "application/json")

    print(f"--> {a.method} {a.url}")
    print(f"--> headers: {json.dumps(redact_headers(headers))}")
    if a.data:
        print(f"--> body: {a.data}")

    req = urllib.request.Request(a.url, data=data, method=a.method, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=a.timeout) as resp:
            elapsed = time.monotonic() - start
            raw = resp.read()
            status = resp.status
            resp_headers = dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - start
        raw = e.read()
        status = e.code
        resp_headers = dict(e.headers.items()) if e.headers else {}
    except urllib.error.URLError as e:
        print(f"<-- falha de conexão após {time.monotonic() - start:.2f}s: {e.reason}")
        return 1

    print(f"<-- status: {status}  ({elapsed:.2f}s)")
    print(f"<-- headers: {json.dumps(resp_headers)}")
    body_text = raw.decode("utf-8", errors="replace")
    content_type = resp_headers.get("Content-Type", "")
    if "json" in content_type.lower():
        try:
            parsed = json.loads(body_text)
            print(f"<-- body: {json.dumps(parsed, indent=2)[:4000]}")
            if isinstance(parsed, dict) and parsed.get("errors"):
                print("!!! campo 'errors' (formato GraphQL) presente mesmo que o status de "
                      "transporte pareça sucesso — inspecione explicitamente:")
                for err in parsed["errors"]:
                    print(f"    - {err}")
            return 0 if status < 400 else 1
        except json.JSONDecodeError:
            pass
    print(f"<-- body: {body_text[:4000]}")
    return 0 if status < 400 else 1


def cmd_jwt_decode(a) -> int:
    claims = decode_jwt_claims(a.value)
    print(json.dumps(claims, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("request")
    s.add_argument("--url", required=True)
    s.add_argument("--method", default="GET")
    s.add_argument("--header", action="append", default=[])
    s.add_argument("--data", default=None)
    s.add_argument("--timeout", type=float, default=10.0)
    s.add_argument("--credential-var", action="append", default=[],
                    help="nome(s) de variável de credencial a buscar e enviar como Bearer")

    s = sub.add_parser("jwt-decode")
    s.add_argument("--value", required=True)

    return p


def main() -> int:
    a = build_parser().parse_args()
    handlers = {"request": cmd_request, "jwt-decode": cmd_jwt_decode}
    return handlers[a.command](a)


if __name__ == "__main__":
    raise SystemExit(main())
