"""Cadeia de matching fuzzy p/ edição de arquivo — paridade Hermes (tools/fuzzy_match.py).

Substitui o fallback único (whitespace-só, via patch._find_block) por uma cadeia de 9
estratégias, tentadas em ORDEM, parando na primeira que casar:

    1. exact                  — string idêntica
    2. line_trimmed            — cada linha strip() antes de comparar
    3. whitespace_normalized   — espaços/tabs internos colapsados
    4. indentation_flexible    — ignora indentação (lstrip por linha)
    5. escape_normalized       — \\n/\\t/\\r literais → caractere real
    6. trimmed_boundary        — só a 1ª e a última linha do bloco são strip()
    7. unicode_normalized      — aspas curvas/travessão/nbsp → ASCII (reusa patch._uni_norm)
    8. block_anchor            — âncora na 1ª+última linha, similaridade no meio
    9. context_aware           — ≥50% das linhas com similaridade ≥80%

`replace_all` decide o que fazer com múltiplos matches: sem ele, >1 match é AMBÍGUO (recusa,
não escolhe sozinho — mesma postura do patch._find_block). As posições retornadas por cada
estratégia são SEMPRE (start, end) no texto ORIGINAL — a substituição é feita colando contra
os bytes originais, nunca contra a versão normalizada (senão corrompe o resto do arquivo).

Duas guardas (também portadas do Hermes) evitam que um match não-exato corrompa o arquivo:
- escape-drift: `\\'`/`\\"` presentes em old/new mas ausentes na região casada → provável
  artefato de serialização do tool-call (aspas com barra invertida espúria) — recusa.
- unicode-preservation: quando quem casou foi `unicode_normalized`, a região do arquivo
  tem unicode "bonito" que o `new` (ASCII) apagaria — realinha o replace pra preservar o
  unicode fora do trecho realmente alterado (via diff old→new).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable

Span = tuple[int, int]


# Tabela unicode→ASCII "bonito → reto" (aspas curvas, travessão/meia-risca, reticências, espaços
# especiais). Paridade Hermes: em-dash '—' → '--' (2 chars) — por isso a cadeia usa mapeamento por
# POSIÇÃO (_build_orig_to_norm_map), não 1:1. Cópia PRÓPRIA (não importa de patch.py): o parser V4A
# tem sua própria tabela pro matching por LINHA do apply_patch, e as duas evoluem independentemente
# — importar em runtime criaria acoplamento entre módulos de dono/tarefa diferentes.
UNICODE_MAP: dict[str, str] = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # aspas simples curvas
    "“": '"', "”": '"', "„": '"', "‟": '"',   # aspas duplas curvas
    "–": "-", "—": "--", "―": "-", "−": "-",  # en-dash/em-dash/horiz.bar/minus
    "…": "...", " ": " ", " ": " ", " ": " ", "​": "",
}


def _unicode_map() -> dict[str, str]:
    return UNICODE_MAP


def _unicode_normalize(text: str) -> str:
    """Aplica UNICODE_MAP e depois COLAPSA hífens repetidos ('--', '---'...) em um só.

    O em-dash mapeia p/ '--' (2 chars), mas o modelo às vezes já digita '--' OU '-' ASCII pra
    representar o mesmo travessão — sem colapsar, um lado normaliza pra '-' e o outro pra '--' e
    o match falha por 1 caractere. Colapsar os dois lados pro mesmo '-' canônico faz o `old` casar
    seja qual for a convenção que o modelo (ou o arquivo) usou."""
    m = _unicode_map()
    for char, repl in m.items():
        text = text.replace(char, repl)
    return re.sub(r"-{2,}", "-", text)


def fuzzy_find_and_replace(
    content: str, old_string: str, new_string: str, replace_all: bool = False,
) -> tuple[str, int, str | None, str | None]:
    """Acha e substitui `old_string` em `content` andando a cadeia de estratégias.

    Retorna (novo_conteúdo, nº_de_substituições, nome_da_estratégia, erro).
    Sucesso: erro é None. Falha: novo_conteúdo == content, nº == 0, estratégia None.
    """
    if not old_string:
        return content, 0, None, "old_string vazio"
    if old_string == new_string:
        return content, 0, None, "old_string e new_string são idênticos"

    strategies: list[tuple[str, Callable[[str, str], list[Span]]]] = [
        ("exact", _strategy_exact),
        ("line_trimmed", _strategy_line_trimmed),
        ("whitespace_normalized", _strategy_whitespace_normalized),
        ("indentation_flexible", _strategy_indentation_flexible),
        ("escape_normalized", _strategy_escape_normalized),
        ("trimmed_boundary", _strategy_trimmed_boundary),
        ("unicode_normalized", _strategy_unicode_normalized),
        ("block_anchor", _strategy_block_anchor),
        ("context_aware", _strategy_context_aware),
    ]

    for name, fn in strategies:
        matches = fn(content, old_string)
        if not matches:
            continue
        if len(matches) > 1 and not replace_all:
            return content, 0, None, (
                f"Found {len(matches)} matches for old_string. Provide more context to make it "
                f"unique, or use replace_all=True."
            )

        if name != "exact":
            drift = _detect_escape_drift(content, matches, old_string, new_string)
            if drift:
                return content, 0, None, drift

        effective_new = _maybe_unescape_new_string(new_string, content, matches)
        if name == "unicode_normalized":
            effective_new = _preserve_unicode_in_replacement(content, matches, old_string, effective_new)

        new_content = _apply_replacements(
            content, matches, effective_new, old_string=old_string if name != "exact" else None,
        )
        return new_content, len(matches), name, None

    return content, 0, None, "Could not find a match for old_string in the file"


# --------------------------------------------------------------------------- guardas


def _detect_escape_drift(content: str, matches: list[Span], old_string: str, new_string: str) -> str | None:
    """`\\'`/`\\"` em old E new mas ausentes na região casada → drift de serialização do tool-call
    (apóstrofo/aspas ganhando barra invertida espúria no transporte). Recusa em vez de gravar lixo."""
    if "\\'" not in new_string and '\\"' not in new_string:
        return None
    matched_regions = "".join(content[s:e] for s, e in matches)
    for suspect in ("\\'", '\\"'):
        if suspect in new_string and suspect in old_string and suspect not in matched_regions:
            plain = suspect[1]
            return (
                f"Escape-drift detectado: old/new contêm a sequência literal {suspect!r} mas a região "
                f"casada do arquivo não. É quase sempre artefato de serialização (aspas/apóstrofo "
                f"ganhando barra invertida espúria). Releia o arquivo e passe old/new sem escapar "
                f"{plain!r}."
            )
    return None


def _leading_ws(line: str) -> str:
    i = 0
    while i < len(line) and line[i] in (" ", "\t"):
        i += 1
    return line[:i]


def _first_meaningful_line(text: str) -> str | None:
    for line in text.split("\n"):
        if line.strip():
            return line
    return None


def _reindent_replacement(file_region: str, old_string: str, new_string: str) -> str:
    """Realinha `new_string` p/ a indentação REAL do arquivo quando o match veio de estratégia
    não-exata (o modelo pode ter mandado old/new com indent diferente do disco)."""
    if not new_string:
        return new_string
    old_first = _first_meaningful_line(old_string)
    file_first = _first_meaningful_line(file_region)
    if old_first is None or file_first is None:
        return new_string
    old_indent = _leading_ws(old_first)
    file_indent = _leading_ws(file_first)
    if old_indent == file_indent:
        return new_string
    out: list[str] = []
    for line in new_string.split("\n"):
        if not line.strip():
            out.append(line)
            continue
        line_indent = _leading_ws(line)
        if line_indent.startswith(old_indent):
            out.append(file_indent + line[len(old_indent):])
        else:
            out.append(file_indent + line.lstrip(" \t"))
    return "\n".join(out)


def _maybe_unescape_new_string(new_string: str, content: str, matches: list[Span]) -> str:
    """`\\t`/`\\r` literais no new_string → caractere real, MAS só quando a região casada do
    arquivo já tem o byte de controle real (senão é string Python legítima com "\\t" literal)."""
    if "\\t" not in new_string and "\\r" not in new_string:
        return new_string
    matched_regions = "".join(content[s:e] for s, e in matches)
    out = new_string
    if "\\t" in out and "\t" in matched_regions:
        out = out.replace("\\t", "\t")
    if "\\r" in out and "\r" in matched_regions:
        out = out.replace("\\r", "\r")
    return out


def _build_orig_to_norm_map(original: str) -> list[int]:
    """orig_to_norm[i] = posição normalizada do caractere i (mapeamentos unicode podem EXPANDIR:
    em-dash → '...' etc. — por isso não dá pra assumir 1:1)."""
    m = _unicode_map()
    out: list[int] = []
    pos = 0
    for ch in original:
        out.append(pos)
        repl = m.get(ch)
        pos += len(repl) if repl is not None else 1
    out.append(pos)
    return out


def _map_positions_norm_to_orig(orig_to_norm: list[int], norm_matches: list[Span]) -> list[Span]:
    norm_to_orig_start: dict[int, int] = {}
    for orig_pos, norm_pos in enumerate(orig_to_norm[:-1]):
        norm_to_orig_start.setdefault(norm_pos, orig_pos)
    orig_len = len(orig_to_norm) - 1
    results: list[Span] = []
    for norm_start, norm_end in norm_matches:
        if norm_start not in norm_to_orig_start:
            continue
        orig_start = norm_to_orig_start[norm_start]
        orig_end = orig_start
        while orig_end < orig_len and orig_to_norm[orig_end] < norm_end:
            orig_end += 1
        results.append((orig_start, orig_end))
    return results


def _preserve_unicode_in_replacement(
    content: str, matches: list[Span], old_string: str, new_string: str,
) -> str:
    """Quando quem casou foi `unicode_normalized`, o arquivo tem unicode "bonito" que old/new (ASCII)
    não têm. Grava new_string verbatim apagaria o unicode das partes NÃO alteradas — em vez disso,
    faz diff old→new e aplica só as edições de fato, preservando unicode do arquivo no resto."""
    file_region = "".join(content[s:e] for s, e in matches)
    norm_old = _unicode_normalize(old_string)
    norm_file = _unicode_normalize(file_region)
    if norm_old != norm_file:
        return new_string  # não deveria ter casado — devolve sem tentar realinhar

    file_orig_to_norm = _build_orig_to_norm_map(file_region)
    file_norm_to_orig: dict[int, int] = {}
    for orig_pos, np in enumerate(file_orig_to_norm[:-1]):
        file_norm_to_orig.setdefault(np, orig_pos)

    sm = SequenceMatcher(None, norm_old, new_string)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            orig_start = file_norm_to_orig.get(i1, 0)
            orig_end = orig_start
            while orig_end < len(file_region) and file_orig_to_norm[orig_end] < i2:
                orig_end += 1
            parts.append(file_region[orig_start:orig_end])
        elif tag in ("replace", "insert"):
            parts.append(new_string[j1:j2])
        # "delete": nada — trecho removido
    return "".join(parts)


def _apply_replacements(content: str, matches: list[Span], new_string: str, old_string: str | None = None) -> str:
    """Cola `new_string` nas posições casadas — SEMPRE contra o `content` ORIGINAL (nunca contra
    versão normalizada). `old_string` não-None sinaliza match não-exato → reindenta antes de colar."""
    sorted_matches = sorted(matches, key=lambda x: x[0], reverse=True)
    result = content
    for start, end in sorted_matches:
        if old_string is not None:
            adjusted = _reindent_replacement(content[start:end], old_string, new_string)
        else:
            adjusted = new_string
        result = result[:start] + adjusted + result[end:]
    return result


# --------------------------------------------------------------------------- estratégias


def _strategy_exact(content: str, pattern: str) -> list[Span]:
    matches = []
    start = 0
    while True:
        pos = content.find(pattern, start)
        if pos == -1:
            break
        matches.append((pos, pos + len(pattern)))
        start = pos + len(pattern)          # avança o bloco inteiro — não sobrepõe (semântica str.replace)
    return matches


def _strategy_line_trimmed(content: str, pattern: str) -> list[Span]:
    pattern_lines = [ln.strip() for ln in pattern.split("\n")]
    content_lines = content.split("\n")
    content_normalized_lines = [ln.strip() for ln in content_lines]
    return _find_normalized_matches(content, content_lines, content_normalized_lines,
                                     "\n".join(pattern_lines))


def _strategy_whitespace_normalized(content: str, pattern: str) -> list[Span]:
    def normalize(s: str) -> str:
        return re.sub(r"[ \t]+", " ", s)

    pattern_normalized = normalize(pattern)
    content_normalized = normalize(content)
    matches_in_normalized = _strategy_exact(content_normalized, pattern_normalized)
    if not matches_in_normalized:
        return []
    return _map_ws_normalized_positions(content, content_normalized, matches_in_normalized)


def _strategy_indentation_flexible(content: str, pattern: str) -> list[Span]:
    content_lines = content.split("\n")
    content_stripped_lines = [ln.lstrip() for ln in content_lines]
    pattern_lines = [ln.lstrip() for ln in pattern.split("\n")]
    return _find_normalized_matches(content, content_lines, content_stripped_lines,
                                     "\n".join(pattern_lines))


def _strategy_escape_normalized(content: str, pattern: str) -> list[Span]:
    def unescape(s: str) -> str:
        return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    unescaped = unescape(pattern)
    if unescaped == pattern:
        return []
    return _strategy_exact(content, unescaped)


def _strategy_trimmed_boundary(content: str, pattern: str) -> list[Span]:
    pattern_lines = pattern.split("\n")
    if not pattern_lines:
        return []
    pattern_lines = list(pattern_lines)
    pattern_lines[0] = pattern_lines[0].strip()
    if len(pattern_lines) > 1:
        pattern_lines[-1] = pattern_lines[-1].strip()
    modified_pattern = "\n".join(pattern_lines)

    content_lines = content.split("\n")
    matches: list[Span] = []
    n = len(pattern_lines)
    for i in range(len(content_lines) - n + 1):
        block = content_lines[i:i + n].copy()
        block[0] = block[0].strip()
        if len(block) > 1:
            block[-1] = block[-1].strip()
        if "\n".join(block) == modified_pattern:
            matches.append(_calc_line_positions(content_lines, i, i + n, len(content)))
    return matches


def _strategy_unicode_normalized(content: str, pattern: str) -> list[Span]:
    norm_pattern = _unicode_normalize(pattern)
    norm_content = _unicode_normalize(content)
    if norm_content == content and norm_pattern == pattern:
        return []
    norm_matches = _strategy_exact(norm_content, norm_pattern)
    if not norm_matches:
        norm_matches = _strategy_line_trimmed(norm_content, norm_pattern)
    if not norm_matches:
        return []
    orig_to_norm = _build_orig_to_norm_map(content)
    return _map_positions_norm_to_orig(orig_to_norm, norm_matches)


def _strategy_block_anchor(content: str, pattern: str) -> list[Span]:
    """Âncora na 1ª+última linha (normalizadas p/ unicode), similaridade no meio via SequenceMatcher.
    Threshold mais apertado (0.70) quando há várias âncoras candidatas — evita casar bloco errado."""
    norm_pattern = _unicode_normalize(pattern)
    norm_content = _unicode_normalize(content)
    pattern_lines = norm_pattern.split("\n")
    if len(pattern_lines) < 2:
        return []
    first_line = pattern_lines[0].strip()
    last_line = pattern_lines[-1].strip()

    norm_content_lines = norm_content.split("\n")
    orig_content_lines = content.split("\n")
    n = len(pattern_lines)

    candidates = [
        i for i in range(len(norm_content_lines) - n + 1)
        if norm_content_lines[i].strip() == first_line and norm_content_lines[i + n - 1].strip() == last_line
    ]
    threshold = 0.50 if len(candidates) == 1 else 0.70

    matches: list[Span] = []
    for i in candidates:
        if n <= 2:
            similarity = 1.0
        else:
            content_middle = "\n".join(norm_content_lines[i + 1:i + n - 1])
            pattern_middle = "\n".join(pattern_lines[1:-1])
            similarity = SequenceMatcher(None, content_middle, pattern_middle).ratio()
        if similarity >= threshold:
            matches.append(_calc_line_positions(orig_content_lines, i, i + n, len(content)))
    return matches


def _strategy_context_aware(content: str, pattern: str) -> list[Span]:
    """≥50% das linhas do bloco com similaridade (strip) ≥80% viram match — última rede de segurança
    antes de desistir; propositalmente frouxa, mas ainda exige a MAIORIA das linhas parecidas.

    DESVIO do Hermes: exige `pattern` com >=3 linhas. Em blocos de 2 linhas, `n*0.5` arredonda pra
    1 — ou seja, 1 linha idêntica + 1 TOTALMENTE diferente já bastava pra "casar" e corromper a
    linha errada (verificado com fixture real: 'def hello(): / return NOPE' quase casou contra
    'def hello(): / return hi'). Bloco pequeno demais pra essa rede de segurança valer o risco.
    """
    pattern_lines = pattern.split("\n")
    content_lines = content.split("\n")
    if len(pattern_lines) < 3:
        return []
    n = len(pattern_lines)
    matches: list[Span] = []
    for i in range(len(content_lines) - n + 1):
        block = content_lines[i:i + n]
        high_sim = sum(
            1 for p_line, c_line in zip(pattern_lines, block)
            if SequenceMatcher(None, p_line.strip(), c_line.strip()).ratio() >= 0.80
        )
        if high_sim >= n * 0.5:
            matches.append(_calc_line_positions(content_lines, i, i + n, len(content)))
    return matches


# --------------------------------------------------------------------------- helpers de posição


def _calc_line_positions(content_lines: list[str], start_line: int, end_line: int, content_length: int) -> Span:
    start_pos = sum(len(ln) + 1 for ln in content_lines[:start_line])
    end_pos = sum(len(ln) + 1 for ln in content_lines[:end_line]) - 1
    return start_pos, min(content_length, end_pos)


def _find_normalized_matches(content: str, content_lines: list[str], content_normalized_lines: list[str],
                              pattern_normalized: str) -> list[Span]:
    pattern_norm_lines = pattern_normalized.split("\n")
    n = len(pattern_norm_lines)
    matches: list[Span] = []
    for i in range(len(content_normalized_lines) - n + 1):
        if "\n".join(content_normalized_lines[i:i + n]) == pattern_normalized:
            matches.append(_calc_line_positions(content_lines, i, i + n, len(content)))
    return matches


def _map_ws_normalized_positions(original: str, normalized: str, normalized_matches: list[Span]) -> list[Span]:
    """Mapeia posições da string com whitespace colapsado (espaço/tab→espaço único) de volta pro
    original — melhor esforço, caractere a caractere."""
    if not normalized_matches:
        return []
    orig_to_norm: list[int] = []
    orig_idx = norm_idx = 0
    while orig_idx < len(original) and norm_idx < len(normalized):
        if original[orig_idx] == normalized[norm_idx]:
            orig_to_norm.append(norm_idx)
            orig_idx += 1
            norm_idx += 1
        elif original[orig_idx] in " \t" and normalized[norm_idx] == " ":
            orig_to_norm.append(norm_idx)
            orig_idx += 1
            if orig_idx < len(original) and original[orig_idx] not in " \t":
                norm_idx += 1
        elif original[orig_idx] in " \t":
            orig_to_norm.append(norm_idx)
            orig_idx += 1
        else:
            orig_to_norm.append(norm_idx)
            orig_idx += 1
    while orig_idx < len(original):
        orig_to_norm.append(len(normalized))
        orig_idx += 1

    norm_to_orig_start: dict[int, int] = {}
    norm_to_orig_end: dict[int, int] = {}
    for orig_pos, norm_pos in enumerate(orig_to_norm):
        norm_to_orig_start.setdefault(norm_pos, orig_pos)
        norm_to_orig_end[norm_pos] = orig_pos

    results: list[Span] = []
    for norm_start, norm_end in normalized_matches:
        if norm_start in norm_to_orig_start:
            orig_start = norm_to_orig_start[norm_start]
        else:
            candidates = [i for i, n in enumerate(orig_to_norm) if n >= norm_start]
            orig_start = min(candidates) if candidates else 0
        if norm_end - 1 in norm_to_orig_end:
            orig_end = norm_to_orig_end[norm_end - 1] + 1
        else:
            orig_end = orig_start + (norm_end - norm_start)
        if norm_end < len(normalized) and normalized[norm_end - 1] == " ":
            while orig_end < len(original) and original[orig_end] in " \t":
                orig_end += 1
        results.append((orig_start, min(orig_end, len(original))))
    return results


# --------------------------------------------------------------------------- did-you-mean (top-N)


def find_closest_lines(old_string: str, content: str, context_lines: int = 2, max_results: int = 3) -> str:
    """Top-`max_results` trechos do arquivo mais parecidos com `old_string` (ancorado na 1ª linha
    não-vazia), formatados com nº de linha, p/ o modelo copiar literal. '' se nada útil."""
    if not old_string or not content:
        return ""
    old_lines = old_string.splitlines()
    content_lines = content.splitlines()
    if not old_lines or not content_lines:
        return ""

    anchor = old_lines[0].strip()
    if not anchor:
        candidates = [ln.strip() for ln in old_lines if ln.strip()]
        if not candidates:
            return ""
        anchor = candidates[0]

    scored: list[tuple[float, int]] = []
    for i, line in enumerate(content_lines):
        stripped = line.strip()
        if not stripped:
            continue
        ratio = SequenceMatcher(None, anchor, stripped).ratio()
        if ratio > 0.3:
            scored.append((ratio, i))
    if not scored:
        return ""

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_results]

    parts: list[str] = []
    seen_ranges: set[tuple[int, int]] = set()
    for _, line_idx in top:
        start = max(0, line_idx - context_lines)
        end = min(len(content_lines), line_idx + len(old_lines) + context_lines)
        key = (start, end)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        snippet = "\n".join(f"{start + j + 1:4d}| {content_lines[start + j]}" for j in range(end - start))
        parts.append(snippet)

    return "\n---\n".join(parts) if parts else ""


def format_no_match_hint(error: str | None, match_count: int, old_string: str, content: str) -> str:
    """'\\n\\nDid you mean...' só p/ no-match GENUÍNO (match_count==0 E erro de 'não achei') — ambíguo/
    escape-drift/idênticos também têm match_count==0 mas o hint seria enganoso ali."""
    if match_count != 0:
        return ""
    if not error or not error.startswith("Could not find"):
        return ""
    hint = find_closest_lines(old_string, content)
    if not hint:
        return ""
    return "\n\nDid you mean one of these sections?\n" + hint
