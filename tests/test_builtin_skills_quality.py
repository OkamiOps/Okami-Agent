"""Auditoria de QUALIDADE das skills nativas (não só mecanismo): dois incidentes reais motivaram
isto —

1. Uma skill de PDF/HTML mandou o agente subir `puppeteer.launch()`/Chromium num caminho onde já
   existe tool NATIVA (`generate_pdf`, pura-Python via xhtml2pdf/fpdf2). Numa VPS sem display isso
   falha (sandbox do Chromium, errno -88) e mesmo quando funciona é muito mais lento. Nenhuma
   skill nativa deve recomendar Puppeteer/Playwright/Chromium para gerar PDF.
2. O agente saiu vasculhando arquivo de credencial no disco (Google/OAuth) em vez de pedir ao dono
   pelo canal seguro (`store_secret`). As skills que lidam com credencial precisam deixar isso
   explícito: PEDIR ao dono, nunca caçar arquivo, nunca propor `--yolo`/bypass de sandbox.

Este teste cobre: (a) nenhum SKILL.md nativo recomenda puppeteer/playwright/chromium para PDF,
(b) a skill de PDF menciona `generate_pdf`, (c) o princípio "peça ao dono, nunca vasculhe/yolo"
está presente nas skills que mexem com credencial, (d) toda skill nativa continua parseável e
passa limpo (não-bloqueada) no security scan — senão `with_builtin` a descarta silenciosamente.
"""
from __future__ import annotations

import re

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()


def _all_skill_md_texts() -> dict[str, str]:
    return {md.parent.name: md.read_text(encoding="utf-8") for md in sorted(ROOT.rglob("SKILL.md"))}


def test_no_builtin_skill_recommends_headless_browser_for_pdf():
    """Nenhum SKILL.md nativo pode instruir o agente a usar Puppeteer/Playwright/Chromium para
    lidar com PDF — a tool nativa `generate_pdf` cobre HTML/markdown → PDF sem browser. Mencionar
    essas palavras em contexto NÃO relacionado a PDF (ex.: navegação web com JS pesado) é ok."""
    bad_pattern = re.compile(r"puppeteer|playwright|chromium", re.IGNORECASE)
    for name, text in _all_skill_md_texts().items():
        # ignora o frontmatter YAML (triggers/intent_examples podem citar a palavra como GATILHO,
        # não como recomendação — o corpo da skill é o que importa aqui).
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        for m in bad_pattern.finditer(body):
            window = re.sub(r"\s+", " ", body[max(0, m.start() - 160): m.end() + 60])
            window_lower = window.lower()
            if "pdf" not in window_lower:
                continue  # não é sobre PDF (ex.: browse/web genérico) — fora de escopo aqui.
            # Perto de "pdf", só é aceitável se vier negado/desencorajado.
            negated = any(neg in window_lower for neg in
                          ("sem ", "não ", "nunca", "evita", "prefira", "improvisado", "antes de instalar"))
            assert negated, (
                f"{name}/SKILL.md recomenda '{m.group(0)}' perto de 'pdf' sem negação — "
                f"prefira a tool nativa (generate_pdf) em vez de browser headless.\n"
                f"contexto: ...{window}..."
            )


def test_pdf_skill_mentions_generate_pdf_tool():
    texts = _all_skill_md_texts()
    assert "editar-pdf" in texts
    assert "generate_pdf" in texts["editar-pdf"], (
        "a skill de PDF deve apontar para a tool nativa `generate_pdf` (HTML/markdown → PDF) "
        "em vez de deixar o agente improvisar um caminho externo"
    )


def test_credential_principle_present_in_credential_skills():
    texts = _all_skill_md_texts()
    principle_markers = ("store_secret", "peça ao dono", "pedir ao dono", "canal seguro")
    anti_markers = ("yolo", "vasculhe", "vasculh")

    # a skill dedicada ao princípio precisa existir e conter as duas regras.
    assert "ferramentas-nativas-primeiro" in texts, "falta a skill de princípio ferramentas-nativas-primeiro"
    principle_text = texts["ferramentas-nativas-primeiro"].lower()
    assert any(m in principle_text for m in principle_markers)
    assert any(m in principle_text for m in anti_markers)
    assert "yolo" in principle_text

    # as skills que de fato lidam com credencial/acesso também precisam reforçar o princípio.
    for name in ("acesso-vps", "github"):
        assert name in texts, f"skill {name} não encontrada"
        t = texts[name].lower()
        assert any(m in t for m in principle_markers), f"{name}/SKILL.md não menciona pedir credencial ao dono"
        assert "yolo" in t, f"{name}/SKILL.md não menciona explicitamente não propor --yolo"


def test_all_builtin_skills_parse_with_expected_fields():
    bs = load_builtin_skills()
    assert bs, "nenhuma skill nativa carregada"
    for sk in bs:
        assert sk.name and sk.description, f"skill sem name/description: {sk}"
        cat = catalog([sk])
        assert sk.name in cat


def test_all_builtin_skills_scan_clean():
    for md in sorted(ROOT.rglob("SKILL.md")):
        skill_dir = md.parent
        report = scan_path(skill_dir)
        assert not report.blocked, (skill_dir.name, [str(f) for f in report.sorted()])
