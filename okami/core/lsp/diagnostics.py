"""Delta semântico (pesquisa #7 item 16) — espelha o contrato "só NOVO" do `lint_delta`.

`lsp_delta(workspace, rel, before, after)` roda pyright nos dois conteúdos e avisa SÓ os erros
que o `after` introduziu (que o `before` não tinha). Editar um arquivo que JÁ tinha o erro não
nagueia — igual ao lint stdlib do item 6.

Chave do diagnóstico = (mensagem normalizada, símbolo aproximado), NÃO o número da linha: inserir
linhas acima desloca todos os erros para baixo, e isso não pode virar "erro novo" falso. O símbolo
é extraído da mensagem do pyright (ex.: `"foo" is not defined` → foo) — heurística, suficiente p/
distinguir "outro nome quebrou" de "o mesmo erro andou de linha".

Fail-open em CASCATA: "" a menos que o workspace seja um projeto git, pyright esteja disponível e
o arquivo seja .py. Qualquer exceção → "". Nunca levanta, nunca bloqueia.
"""
from __future__ import annotations

import re
from pathlib import Path

from okami.core.lsp import pyright_client

# severidade LSP: 1=Error, 2=Warning, 3=Info, 4=Hint. Só nagueamos ERRO (ruído mata o sinal).
_SEVERITY_ERROR = 1

# símbolo entre aspas na mensagem do pyright: `"foo" is not defined`, `Import "bar" could not…`
_SYMBOL_RE = re.compile(r'"([^"]+)"')


def _key(diag: dict) -> tuple[str, str]:
    """Chave estável de um diagnóstico: (mensagem sem o símbolo, símbolo). Linha NÃO entra."""
    msg = str(diag.get("message") or "").strip()
    m = _SYMBOL_RE.search(msg)
    symbol = m.group(1) if m else ""
    # tira o símbolo do corpo da mensagem p/ a chave não depender de QUAL nome, só do TIPO de erro…
    # mas mantém o símbolo como 2ª parte da tupla (é ele que distingue "foo quebrou" de "bar quebrou").
    body = _SYMBOL_RE.sub('""', msg)
    return (body, symbol)


def _error_keys(diags: list[dict]) -> set[tuple[str, str]]:
    return {_key(d) for d in diags if int(d.get("severity") or _SEVERITY_ERROR) == _SEVERITY_ERROR}


def _is_python(rel: str) -> bool:
    return Path(str(rel)).suffix.lower() == ".py"


def lsp_delta(workspace, rel: str, before: str, after: str) -> str:
    """Aviso PT dos erros SEMÂNTICOS NOVOS que a escrita introduziu, ou "" se nenhum / inaplicável.

    Pré-condições (todas fail-open → ""): workspace é projeto git (.git existe), pyright disponível,
    `rel` termina em .py. Erros que já existiam no `before` (mesma chave msg+símbolo) não nagueiam.
    """
    try:
        ws = Path(workspace)
        if not (ws / ".git").exists():                     # não é projeto → fora de escopo
            return ""
        if not _is_python(rel):                            # só Python tem semântica via pyright
            return ""
        if pyright_client.find_binary() is None:           # sem binário → silencioso
            return ""

        after_keys = _error_keys(pyright_client.diagnose(ws, rel, after))
        if not after_keys:                                 # after limpo → nada a avisar
            return ""
        before_keys = _error_keys(pyright_client.diagnose(ws, rel, before or ""))
        novos = after_keys - before_keys                   # chaves só no after = erros NOVOS
        if not novos:
            return ""

        # mensagem de 1 linha por erro novo (símbolo quando há; senão o corpo)
        partes = [sym or body for body, sym in sorted(novos)]
        return f"⚠ lsp: {rel}: {'; '.join(partes)} — nome/símbolo sem definição (pyright)"
    except Exception:  # noqa: BLE001 — qualquer coisa: fail-open total
        return ""
