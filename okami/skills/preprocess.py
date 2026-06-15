"""Pré-processamento do corpo da SKILL.md no load — expansão SEGURA de variáveis ${OKAMI_*}.

Sem shell, de propósito (segurança): nada de $(...) nem `...` — só substituímos um conjunto FECHADO
de placeholders ${NOME} por valores conhecidos. Variável fora dessa lista (ex.: ${OUTRA}) fica intacta,
e qualquer substituição de comando estilo `!`rm -rf`` permanece literal — o corpo da skill é DADO, não
código a executar. Fail-safe: nunca levanta; corpo vazio/não-str é no-op.
"""

from __future__ import annotations

import re
from datetime import date

# Casa SÓ ${NOME} com nome em maiúsculas/underscore — não toca $(...) nem `...` (não há shell aqui).
_VAR_RX = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def expand_skill_body(body: str, *, skill_dir: str = "", session_id: str = "") -> str:
    """Expande ${OKAMI_SKILL_DIR}/${OKAMI_SESSION_ID}/${OKAMI_DATE} no `body` da SKILL.md.

    - ${OKAMI_SKILL_DIR} -> skill_dir   ${OKAMI_SESSION_ID} -> session_id
    - ${OKAMI_DATE}      -> date.today().isoformat()  (YYYY-MM-DD)
    Variável desconhecida fica como está. NÃO executa shell/comando. No-op p/ vazio/não-str."""
    if not body or not isinstance(body, str):
        return body
    # Lista FECHADA: só estes nomes são resolvidos; o resto (ex.: ${OUTRA}) o repl devolve intacto.
    table = {
        "OKAMI_SKILL_DIR": skill_dir or "",
        "OKAMI_SESSION_ID": session_id or "",
        "OKAMI_DATE": date.today().isoformat(),
    }

    def _repl(m: re.Match) -> str:
        # Desconhecido -> devolve o match original (m.group(0)); nunca avalia nada.
        return table.get(m.group(1), m.group(0))

    try:
        return _VAR_RX.sub(_repl, body)
    except Exception:
        # Best-effort: na dúvida, devolve o corpo original sem derrubar o caller.
        return body
