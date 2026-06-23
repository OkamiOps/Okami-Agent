"""Rule-following (sweep #17): ao recusar uma tool ALUCINADA, o loop despejava TODOS os ~60 nomes de tool no
histórico — contradiz a regra do prompt ('não liste nomes de ferramentas') e afoga o modelo fraco. Agora só
sugere as MAIS PRÓXIMAS (ou nada), sem o manual inteiro."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


def _model_facing(messages):
    return " ".join((m.get("content") or "") for m in messages if m.get("role") in ("user", "tool"))


def test_bogus_tool_does_not_dump_whole_registry(tmp_path):
    def gen(messages, schema=None):
        return Completion(text='{"tool":"florbglax","args":{}}', tool_calls=[])   # nome sem match nenhum

    h = Harness(gen, Task(goal="faça algo"), tmp_path, registry=default_registry())
    h.run()                                              # viola até escalar/falhar
    rej = _model_facing(h.messages)
    assert "florbglax" in rej                            # diz qual foi o inválido
    # NÃO despeja o manual: tools não-relacionadas não aparecem na mensagem de erro
    assert "remember_user" not in rej
    assert "vision_analyze" not in rej
