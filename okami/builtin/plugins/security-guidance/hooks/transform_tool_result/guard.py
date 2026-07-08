#!/usr/bin/env python3
"""security-guidance (port do Hermes) — hook transform_tool_result: varre o CÓDIGO que o agente ACABOU
de escrever (write_file / edit_file / apply_patch) por padrões inseguros e devolve um advisory. NÃO-
BLOQUEANTE (port do transform_tool_result do Hermes/security-guidance): o stdout vira texto ANEXADO ao
resultado da tool — o modelo vê no PRÓXIMO turno e se auto-corrige, sem vetar a escrita nem incomodar o
dono ANTES dela (era o antigo hook before_tool, que vetava/avisava cedo demais — invisível pro modelo).
Auto-contido (só stdlib) p/ rodar sob qualquer python do PATH. Lê OKAMI_HOOK_PAYLOAD
(JSON: {tool,args,result}); fail-open (payload quebrado / sem código → exit 0, silêncio). SEMPRE exit 0
— este hook NUNCA veta (não há evento a bloquear; transform_tool_result é observador+anexador).

NÃO substitui as defesas embutidas (Tirith, jail de path, net_guard, approval) — é uma 2ª opinião sobre
o conteúdo, no estilo dos 25 detectores do Hermes (desserialização, injeção, XSS, cripto fraca, segredos).
"""
import json
import os
import re
import sys

_WRITE_TOOLS = {"write_file", "edit_file", "str_replace", "create_file"}

# (rótulo, regex, explicação). Aplicados a todo o código (cruzar linguagens raramente colide).
_RULES = [
    ("eval/exec", r"\b(eval|exec)\s*\(", "execução de código arbitrário — evite eval()/exec() sobre entrada"),
    ("pickle", r"\b(pickle|cPickle|_pickle|marshal|shelve)\s*\.\s*(loads|load)\s*\(",
     "desserialização insegura (pickle/marshal) — RCE com dado não-confiável; use json"),
    ("yaml.load", r"yaml\s*\.\s*load\s*\((?![^)]*Safe)", "yaml.load sem SafeLoader — use yaml.safe_load()"),
    ("os.system", r"\bos\s*\.\s*system\s*\(", "os.system() — injeção de shell; use subprocess com lista de args"),
    ("os.popen", r"\bos\s*\.\s*popen\s*\(", "os.popen() — injeção de shell; use subprocess com lista de args"),
    ("shell=True", r"subprocess\s*\.\s*\w+\([^)]*shell\s*=\s*True",
     "subprocess shell=True — injeção de shell se algum arg vier de entrada"),
    ("tls-verify-off", r"verify\s*=\s*False\b", "verificação TLS desligada (verify=False) — MITM"),
    ("tls-reject-off", r"rejectUnauthorized\s*:\s*false", "TLS rejectUnauthorized:false — MITM"),
    ("ssl-unverified", r"_create_unverified_context", "contexto SSL não-verificado — MITM"),
    ("xss-innerhtml", r"\.innerHTML\s*=", "atribuição a innerHTML — XSS; prefira textContent/sanitização"),
    ("xss-docwrite", r"document\s*\.\s*write\s*\(", "document.write() — XSS"),
    ("xss-react", r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML — XSS se o HTML não for sanitizado"),
    ("weak-random-js", r"Math\s*\.\s*random\s*\(", "Math.random() — aleatoriedade fraca; use crypto p/ tokens"),
    ("weak-hash", r"\b(hashlib\s*\.\s*)?(md5|sha1)\s*\(", "hash fraco (md5/sha1) — use sha256/bcrypt/argon2 p/ senha"),
    ("hardcoded-secret",
     r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?key|token)\b\s*[:=]\s*[\"'][^\"']{6,}[\"']",
     "possível credencial hardcoded — carregue de env/secret store"),
    ("aws-key", r"AKIA[0-9A-Z]{16}", "AWS access key embutida no código"),
    ("private-key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "chave privada embutida no código"),
    ("bearer-token", r"Bearer\s+[A-Za-z0-9._\-]{20,}", "token Bearer hardcoded"),
    ("sql-format", r"(?i)(execute|executemany|cursor\.execute|\.query)\s*\(\s*f?[\"'][^\"']*\b(select|insert|update|delete)\b",
     "SQL montado por f-string/concatenação — injeção; use queries parametrizadas (?)"),
    ("sql-concat", r"(?i)\b(select|insert|update|delete)\b[^\n;]*[\"']\s*\+\s*\w",
     "SQL por concatenação de string — injeção; use queries parametrizadas (?)"),
    ("mktemp", r"tempfile\s*\.\s*mktemp\s*\(", "tempfile.mktemp() — corrida TOCTOU; use mkstemp/NamedTemporaryFile"),
    ("perm-777", r"(chmod\s+(-R\s+)?0?777\b|0o777|S_IRWXO\b)", "permissão 0777 — excessivamente aberta"),
    ("jwt-none", r"[\"']alg[\"']\s*:\s*[\"']none[\"']", "JWT alg=none — assinatura desativada (bypass)"),
    ("debug-on", r"\bDEBUG\s*=\s*True\b", "DEBUG=True — não deixe ligado em produção (vaza stack/segredo)"),
    ("cors-wildcard", r"Access-Control-Allow-Origin[\"']?\s*[:,]\s*[\"']?\*",
     "CORS Access-Control-Allow-Origin: * — origem irrestrita"),
    ("flask-bind-all", r"app\.run\([^)]*host\s*=\s*[\"']0\.0\.0\.0[\"']", "bind em 0.0.0.0 — exposto à rede"),
    ("py2-input", r"(?<!raw_)\binput\s*\(", "input() em código py2 avalia a entrada — risco (não em py3)"),
]
_COMPILED = [(label, re.compile(rx), msg) for label, rx, msg in _RULES]
# segredo "óbvio-placeholder" não é alerta real (reduz ruído do hardcoded-secret)
_PLACEHOLDER = re.compile(r"(?i)(example|placeholder|your[_-]?|changeme|xxxx+|\.\.\.|<.*>|\$\{|os\.environ|getenv)")


def _added_from_patch(patch: str) -> str:
    """Só as linhas ADICIONADAS ('+', exceto o cabeçalho '+++') — o que VAI passar a existir."""
    out = []
    for line in (patch or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
    return "\n".join(out)


def _extract(tool: str, args: dict) -> str:
    if tool == "apply_patch":
        return _added_from_patch(args.get("patch") or "")
    if tool in _WRITE_TOOLS:
        c = args.get("content")
        if not isinstance(c, str):
            c = args.get("new_str") or args.get("text") or ""
        return c if isinstance(c, str) else ""
    return ""


def _scan(code: str) -> list[str]:
    hits, seen = [], set()
    for label, rx, msg in _COMPILED:
        m = rx.search(code)
        if not m or label in seen:
            continue
        if label == "hardcoded-secret":
            line = code[max(0, m.start() - 48):m.end() + 40]   # inclui contexto ANTES (ex.: comentário "example")
            if _PLACEHOLDER.search(line):
                continue                       # valor é placeholder/env → não é segredo real
        seen.add(label)
        hits.append(f"[{label}] {msg}")
    # random padrão usado perto de termo de segurança (token/senha/nonce…) → cripto fraca
    if "weak-random-py" not in seen and re.search(r"\brandom\s*\.\s*(random|randint|choice|randrange|getrandbits)\b", code) \
       and re.search(r"(?i)(token|secret|password|passwd|otp|nonce|salt|session|api[_-]?key)", code):
        hits.append("[weak-random-py] random padrão não é criptográfico — use secrets/os.urandom p/ tokens")
    return hits


def main() -> int:
    raw = os.environ.get("OKAMI_HOOK_PAYLOAD") or (sys.stdin.read() if not sys.stdin.isatty() else "")
    try:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            return 0
    except (ValueError, TypeError):
        return 0                               # payload quebrado → fail-open (nunca imprime nada)
    tool = str(payload.get("tool") or "")
    args = payload.get("args") or {}
    if tool not in _WRITE_TOOLS and tool != "apply_patch":
        return 0
    code = _extract(tool, args if isinstance(args, dict) else {})
    if not code.strip():
        return 0
    hits = _scan(code)
    if not hits:
        return 0                               # limpo → silêncio total, nada anexado ao resultado
    path = args.get("path") or args.get("file") or "(arquivo)"
    # ADVISORY não-bloqueante: cada achado vira uma linha "⚠️ segurança: <explicação>". O stdout inteiro é
    # ANEXADO ao resultado da tool pelo HookManager (transform_tool_result) — o modelo lê e se auto-corrige
    # no próximo turno. Nenhuma regra aqui é CRITICAL o bastante p/ justificar vetar a escrita já feita.
    print(f"⚠️ security-guidance — {path}: {len(hits)} achado(s):")
    for h in hits:
        print(f"  ⚠️ segurança: {h}")
    return 0                                   # NUNCA veta — transform_tool_result é não-bloqueante


if __name__ == "__main__":
    sys.exit(main())
