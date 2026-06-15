"""Testes do pré-processamento do corpo da SKILL.md (expand_skill_body).

Garante a expansão SEGURA das variáveis ${OKAMI_*} no load: substituição de skill_dir,
session_id e data de hoje — e, principalmente, que NADA é executado como shell (segurança):
substituição de comando estilo `!`...`` fica literal, variável desconhecida fica intacta.
"""

from __future__ import annotations

import re
from datetime import date

from okami.skills.preprocess import expand_skill_body

_DATE_RX = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")  # YYYY-MM-DD


def test_expande_skill_dir_e_data():
    body = "scripts em ${OKAMI_SKILL_DIR}/run.sh hoje ${OKAMI_DATE}"
    out = expand_skill_body(body, skill_dir="/x")
    assert "/x/run.sh" in out                 # skill_dir substituído
    assert _DATE_RX.search(out)               # contém uma data YYYY-MM-DD
    assert date.today().isoformat() in out    # e é a data de hoje
    assert "${OKAMI_SKILL_DIR}" not in out
    assert "${OKAMI_DATE}" not in out


def test_expande_session_id():
    out = expand_skill_body("sessão=${OKAMI_SESSION_ID}", session_id="sess-42")
    assert out == "sessão=sess-42"
    assert "${OKAMI_SESSION_ID}" not in out


def test_variavel_desconhecida_fica_intacta():
    body = "valor ${OUTRA} aqui"
    assert expand_skill_body(body) == "valor ${OUTRA} aqui"


def test_nao_executa_shell_substituicao_de_comando_fica_literal():
    # $(...) e `...` (e a forma `!`...``) NÃO podem rodar: ficam literais no corpo.
    body = "perigo $(rm -rf /) e !`rm -rf /` e `whoami`"
    out = expand_skill_body(body, skill_dir="/x")
    assert out == body                        # nada executado, nada alterado


def test_corpo_vazio_e_nao_str_sao_no_op():
    assert expand_skill_body("") == ""
    assert expand_skill_body(None) is None    # type: ignore[arg-type]  fail-safe


def test_default_skill_dir_e_session_vazios():
    # Sem args, ${OKAMI_SKILL_DIR}/${OKAMI_SESSION_ID} viram string vazia (mas DATE expande).
    out = expand_skill_body("[${OKAMI_SKILL_DIR}][${OKAMI_SESSION_ID}][${OKAMI_DATE}]")
    assert out.startswith("[][]")
    assert _DATE_RX.search(out)
