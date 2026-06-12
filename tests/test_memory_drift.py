"""Guard de drift externo da memória (pesquisa #6 item 9, doutrina Hermes memory_tool drift).

MEMORY.md/USER.md podem ser editados POR FORA (patch tool, append por shell, edição manual, sessão
concorrente). O append do Okami é aditivo (não clobbera), mas perda silenciosa ainda pode acontecer
(corrida read-modify-write). Antes de tocar um arquivo que mudou desde a última escrita NOSSA, tira
um .bak (recuperável) — defende contra perda e dá trilha do que havia.
"""
from __future__ import annotations

from okami.memory import files as mf


def _baks(tmp_path):
    d = tmp_path / ".okami" / "memory_bak"
    return sorted(d.glob("MEMORY.md.*")) if d.exists() else []


def test_normal_appends_no_bak(tmp_path):
    # escritas SEQUENCIAIS nossas (sem edição externa) não geram .bak — só drift gera
    mf.append_fact(tmp_path, "fato um")
    mf.append_fact(tmp_path, "fato dois")
    assert _baks(tmp_path) == []
    txt = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "fato um" in txt and "fato dois" in txt


def test_external_edit_triggers_bak(tmp_path):
    mf.append_fact(tmp_path, "fato original")          # 1ª escrita: registra o hash
    # edição EXTERNA (simula patch/shell/manual): muda o conteúdo sem passar por append_fact
    p = tmp_path / "MEMORY.md"
    p.write_text(p.read_text(encoding="utf-8") + "- editado por fora\n", encoding="utf-8")
    mf.append_fact(tmp_path, "fato novo do agente")    # detecta drift → .bak antes de tocar
    baks = _baks(tmp_path)
    assert len(baks) == 1
    backup = baks[0].read_text(encoding="utf-8")
    assert "editado por fora" in backup                # o estado pré-escrita ficou salvo
    # e o append AINDA aconteceu (aditivo, não recusa) — nada foi perdido
    final = p.read_text(encoding="utf-8")
    assert "editado por fora" in final and "fato novo do agente" in final


def test_bak_rotates_keeping_recent(tmp_path):
    mf.append_fact(tmp_path, "base")
    p = tmp_path / "MEMORY.md"
    for i in range(8):                                  # 8 edições externas → 8 .bak, mas rotaciona
        p.write_text(p.read_text(encoding="utf-8") + f"- ext {i}\n", encoding="utf-8")
        mf.append_fact(tmp_path, f"agente {i}")
    assert len(_baks(tmp_path)) <= 5                    # mantém só os recentes (anti-incha)
