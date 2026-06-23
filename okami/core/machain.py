"""HMAC encadeado compartilhado (pesquisa #7 item 5) — tamper-evidence p/ trilhas append-only.

Espelha a primitiva dos checkpoints (gateway/checkpoints._mac/_verify), extraída p/ poder ser
reusada pela trilha de AUDITORIA (harness._audit) sem duplicar a lógica. Cada linha leva um `mac`
encadeado: mac_i = HMAC(key, mac_{i-1} + payload_i). Adulterar/inserir/reordenar uma linha quebra a
cadeia daquele ponto em diante → o leitor sabe a partir de onde NÃO confiar.

Chave por-diretório em `<dir>/.okami/.audit_hmac.key`, 0600 (não fica legível p/ todos). Funções
puras (sem estado): a chave é passada explicitamente, então o mesmo módulo serve auditoria e futuros
journals. Best-effort no I/O da chave (criação 0600 falha em FS exótico → segue sem chmod).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

_KEYNAME = ".audit_hmac.key"


def key_for(base_dir) -> bytes:
    """Chave HMAC do diretório `base_dir` (em `<base_dir>/.okami/.audit_hmac.key`), criada 0600 se faltar.

    Estável entre chamadas: criada uma vez, relida depois. 32 bytes aleatórios (segredo local, nunca
    sai da máquina). Idêntica filosofia da `Checkpoints._load_key`."""
    d = Path(base_dir) / ".okami"
    d.mkdir(parents=True, exist_ok=True)
    keyfile = d / _KEYNAME
    if keyfile.exists():
        return keyfile.read_bytes()
    key = secrets.token_bytes(32)
    keyfile.write_bytes(key)
    try:
        os.chmod(keyfile, 0o600)                        # chave de integridade não fica legível p/ todos
    except OSError:
        pass
    return key


def _payload_bytes(payload: dict) -> bytes:
    """Serialização ESTÁVEL do payload coberto pelo mac (chaves ordenadas, sem o próprio mac)."""
    body = {k: v for k, v in payload.items() if k != "mac"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def mac(key: bytes, prev: str, payload: dict) -> str:
    """mac encadeado de UMA entrada: HMAC(key, prev_mac + payload-menos-mac)."""
    msg = prev.encode("utf-8") + _payload_bytes(payload)
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify(key: bytes, entries: list[dict]) -> list[bool]:
    """True/False por entrada: a cadeia HMAC bate até aqui? Uma quebra contamina todas as seguintes."""
    oks: list[bool] = []
    prev = ""
    broken = False
    for e in entries:
        if broken:
            oks.append(False)
            continue
        expect = mac(key, prev, e)
        ok = hmac.compare_digest(expect, str(e.get("mac", "")))
        oks.append(ok)
        if not ok:
            broken = True                               # do ponto adulterado em diante, nada é confiável
        else:
            prev = expect
    return oks


def _last_mac_in(text: str) -> str:
    """O último `mac` não-vazio do texto jsonl (varre de trás p/ frente; ignora linha malformada)."""
    for ln in reversed(text.splitlines()):
        ln = ln.strip()
        if not ln:
            continue
        try:
            mac = str(json.loads(ln).get("mac", ""))
        except json.JSONDecodeError:
            continue
        if mac:
            return mac
    return ""


_TAIL_BYTES = 65536


def tail_mac(path) -> str:
    """O `mac` da ÚLTIMA linha do arquivo jsonl (p/ encadear o próximo append). "" se vazio/inexistente.

    Lê só a CAUDA via seek (O(k)) — é chamado a CADA snapshot e o rollback chama várias vezes; ler o arquivo
    INTEIRO virava O(n²) num log que só cresce. Tolerante a linha malformada (ignora as que não parseiam)."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > _TAIL_BYTES:
                f.seek(-_TAIL_BYTES, 2)              # só a cauda
                f.readline()                         # 1ª linha provavelmente cortada no meio → descarta
            chunk = f.read()
        last = _last_mac_in(chunk.decode("utf-8", errors="ignore"))
        if last or size <= _TAIL_BYTES:
            return last
        # cauda só tinha mac vazio (patológico) e o arquivo é maior → relê inteiro (correção > velocidade)
        return _last_mac_in(p.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""
