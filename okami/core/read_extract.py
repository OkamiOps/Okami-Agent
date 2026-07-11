"""Extração de texto de .docx/.xlsx/.ipynb (#9 Tier 1) — stdlib pura (zipfile + ElementTree + json).

Office/notebook são ZIPs/JSON estruturados; sem isto o `read_file` os trata como binário e devolve
lixo. Aqui extraímos o texto legível (parágrafos do Word, células do Excel, código+markdown do
Jupyter) sem dependência nova. Best-effort: arquivo corrompido → None (o read_file informa o erro).
"""
from __future__ import annotations

import json
import zipfile
from json import JSONDecodeError
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

EXTRACTABLE_EXTENSIONS = (".docx", ".xlsx", ".ipynb")
_MAX_XLSX_ROWS = 2000
_MAX_XLSX_COLS = 60


def is_extractable(path) -> bool:
    return str(path).lower().endswith(EXTRACTABLE_EXTENSIONS)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def extract_text(path) -> str | None:
    """Texto legível do arquivo, ou None se o tipo não é extraível / o arquivo está corrompido."""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext == ".ipynb":
            return _extract_ipynb(p)
        if ext == ".docx":
            return _extract_docx(p)
        if ext == ".xlsx":
            return _extract_xlsx(p)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError, DefusedXmlException, KeyError, TypeError,
            AttributeError, JSONDecodeError):                # #9 review: .ipynb com JSON-lista/cells-string
        return None
    return None


def _extract_ipynb(p: Path) -> str:
    nb = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(nb, dict):                             # .ipynb malformado (lista/escalar no topo)
        return ""
    out = []
    for cell in (nb.get("cells") or []):
        if not isinstance(cell, dict):
            continue
        src = cell.get("source", "")
        text = "".join(src) if isinstance(src, list) else str(src)
        kind = cell.get("cell_type", "")
        out.append(f"[{kind}]\n{text}".strip() if kind else text.strip())
    return "\n\n".join(x for x in out if x).strip()


def _extract_docx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = []
    for para in root.iter():
        if _localname(para.tag) == "p":
            paras.append("".join(e.text or "" for e in para.iter() if _localname(e.tag) == "t"))
    return "\n".join(paras).strip()


def _extract_xlsx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot:
                if _localname(si.tag) == "si":
                    shared.append("".join(t.text or "" for t in si.iter() if _localname(t.tag) == "t"))
        lines: list[str] = []
        for name in sorted(n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")):
            wroot = ET.fromstring(z.read(name))
            for row in wroot.iter():
                if _localname(row.tag) != "row":
                    continue
                cells = []
                for c in row:
                    if _localname(c.tag) != "c":
                        continue
                    v = next((e.text for e in c if _localname(e.tag) == "v"), None)
                    if c.get("t") == "s" and v is not None and v.isdigit() and int(v) < len(shared):
                        cells.append(shared[int(v)])
                    elif v is not None:
                        cells.append(v)
                    else:                                # inline string (t="inlineStr")
                        cells.append("".join(e.text or "" for e in c.iter() if _localname(e.tag) == "t"))
                lines.append("\t".join(cells[:_MAX_XLSX_COLS]))
                if len(lines) >= _MAX_XLSX_ROWS:
                    return "\n".join(lines).strip() + "\n… (planilha truncada)"
    return "\n".join(lines).strip()
