"""Tools de arquivo + shell: read/write/edit/list/find + run_shell."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult, _SENSITIVE_PATH, _safe_path, shell_has_effect,
)


def _add_line_numbers(text: str, start: int) -> str:
    """Prefixa cada linha com 'N|' (formato Hermes) a partir de `start` (1-based) — FIX 3, usado só quando
    read_file(line_numbers=true). Preserva a quebra final se o texto original terminava com '\\n'."""
    lines = text.splitlines()
    out = "\n".join(f"{start + i}|{ln}" for i, ln in enumerate(lines))
    return out + "\n" if text.endswith("\n") else out


_MAX_LINE_LEN = 2000  # teto por LINHA (paridade Hermes tools/file_operations.py:869-893) — um minificado/
                      # linha gigante não floda o contexto mesmo com o arquivo inteiro dentro do teto geral


def _truncate_long_lines(text: str, max_len: int = _MAX_LINE_LEN) -> str:
    """Corta cada linha individual acima de `max_len` chars, com marcador (paridade Hermes). Não mexe
    no nº de linhas (offset/limit/line_numbers continuam batendo). No-op se nenhuma linha estourar OU se
    o texto é um blob de UMA linha só sem quebra nenhuma (ex.: saída de comando/base64 sem '\\n') — aí
    não é "1 linha gigante entre outras normais" (o alvo real do cap), é o conteúdo inteiro; o teto GERAL
    de arquivo (100_000 chars) já cobre esse caso sem cortar no meio de um blob que o chamador quer inteiro."""
    if "\n" not in text:
        return text
    lines = text.split("\n")
    changed = False
    out = []
    for ln in lines:
        if len(ln) > max_len:
            out.append(ln[:max_len] + f" […] linha truncada {len(ln)} chars […]")
            changed = True
        else:
            out.append(ln)
    return "\n".join(out) if changed else text


def _strip_bom(text: str) -> tuple[str, bool]:
    """(texto sem BOM inicial, tinha BOM?). `read_text_capped` usa utf-8 puro (não utf-8-sig) — o BOM
    (U+FEFF) sobrevive no texto lido e poluiria a 1ª linha (visível ao modelo, quebra o match de `old`)."""
    if text.startswith("﻿"):
        return text[1:], True
    return text, False


def _detect_line_ending(p) -> str | None:
    """Sniffa CRLF vs LF direto dos BYTES em disco — `read_text_capped`/`Path.read_text` fazem
    universal-newline translation (\\r\\n → \\n) e essa info se perde no texto já decodificado.
    None = indeterminado (novo arquivo, vazio, ou sem quebra de linha na amostra)."""
    try:
        sample = p.read_bytes()[:4096]
    except OSError:
        return None
    if b"\r\n" in sample:
        return "\r\n"
    if b"\n" in sample:
        return "\n"
    return None


def _has_bom_on_disk(p) -> bool:
    try:
        return p.read_bytes()[:3] == b"\xef\xbb\xbf"
    except OSError:
        return False


def _restore_line_ending(text: str, target: str) -> str:
    """Reconverte o texto (sempre trabalhado em LF internamente) pro line-ending ORIGINAL do arquivo
    antes de escrever — senão o 1º edit/write num arquivo CRLF (Windows) normaliza silenciosamente
    pra LF. Idempotente: colapsa qualquer \\r\\n/\\r solto pra \\n antes de expandir p/ o alvo."""
    lf = text.replace("\r\n", "\n").replace("\r", "\n")
    return lf.replace("\n", "\r\n") if target == "\r\n" else lf


def _read_did_you_mean(p, rel: str, *, max_results: int = 3) -> str:
    """Quando read_file mira um path que não existe, sugere até 3 nomes PARECIDOS na mesma pasta
    (paridade Hermes _suggest_similar_files) — tira o modelo do loop de re-chutar variação de nome
    ('mian.py' → 'main.py'). '' se a pasta não existir/estiver vazia ou nada bater minimamente."""
    import difflib
    import os
    try:
        siblings = sorted(e.name for e in p.parent.iterdir())
    except OSError:
        return ""
    if not siblings:
        return ""
    matches = difflib.get_close_matches(p.name, siblings, n=max_results, cutoff=0.5)
    if not matches:
        return ""
    prefix = os.path.dirname(rel)
    sug = ", ".join(f"{prefix}/{m}" if prefix else m for m in matches)
    return f" Você quis dizer: {sug}?"


def _as_int(v) -> int | None:
    """Aceita int ou string numérica (o modelo às vezes manda "5"); senão None."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _multi_lang_delta(workspace, rel, before, after) -> str:
    """#19: diagnostics semânticos de OUTRAS linguagens (não-.py) via o LSP persistente — fail-open total
    (sem o subsistema / qualquer erro → "")."""
    try:
        from okami.lsp.session import multi_lang_delta
        return multi_lang_delta(workspace, rel, before, after)
    except Exception:  # noqa: BLE001
        return ""


def _first_changed_line(text: str, old: str, new: str) -> int:
    """Nº (1-based) da 1ª linha que de fato mudou (item 8): linha onde `old` começa + offset da
    1ª divergência dentro do bloco. Sem casar → 1 (fallback inofensivo)."""
    idx = text.find(old)
    if idx < 0:
        return 1
    start = text[:idx].count("\n") + 1
    for i, (a, b) in enumerate(zip(old.splitlines(), new.splitlines())):
        if a != b:
            return start + i
    return start


def _short_diff(before: str, after: str) -> str:
    """Diff unified curto e CAPADO (item 8) — o modelo vê o que mudou sem reler o arquivo. Tira os
    cabeçalhos '--- '/'+++ ' (ruído) e corta em _DIFF_MAX_LINES p/ não despejar arquivo gigante."""
    import difflib
    try:
        from okami.tui import _DIFF_MAX_LINES
    except Exception:  # noqa: BLE001 — tui pode não importar (sem rich); usa um teto sensato
        _DIFF_MAX_LINES = 40
    ud = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=2))
    body = ud[2:] if len(ud) >= 2 else ud            # remove os 2 headers de arquivo ('--- '/'+++ ')
    if not body:
        return ""
    if len(body) > _DIFF_MAX_LINES:
        body = body[:_DIFF_MAX_LINES] + ["… (diff truncado)"]
    return "\n".join(body)


_BIN_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v",
    ".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2", ".xz",
    ".so", ".dll", ".dylib", ".bin", ".exe", ".o", ".a", ".class", ".pyc", ".pyd",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
})
_IMG_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"})


def _binary_guard(rel: str, p):
    """ToolResult de recusa se `p` é binário (extensão conhecida OU NUL nos 1os bytes) — read_file é só p/
    texto; binário viraria mojibake no contexto. Imagem → aponta o vision_analyze. None = é texto, segue."""
    ext = p.suffix.lower()
    binary = ext in _BIN_EXT
    if not binary:
        try:
            from okami.core.tools.search import _is_binary
            binary = _is_binary(p.read_bytes()[:1024])
        except Exception:  # noqa: BLE001 — falha no probe → trata como texto (não bloqueia à toa)
            binary = False
    if not binary:
        return None
    extra = " — é IMAGEM: use vision_analyze para descrevê-la" if ext in _IMG_EXT else ""
    return ToolResult(False, f"'{rel}' parece BINÁRIO ({ext or 'sem extensão'}) — read_file é só p/ "
                      f"texto{extra}.", effect=False)


class ReadFile(Tool):
    name = "read_file"
    description = ("Lê um arquivo de texto do workspace. Opcional: offset (pular N linhas) + limit "
                   "(ler só N linhas) p/ paginar arquivo/saída grande sem trazer tudo de uma vez.")
    args_schema = {"path": "caminho relativo ao workspace",
                   "offset": "(opcional) nº de linhas a pular do início",
                   "limit": "(opcional) máx. de linhas a retornar",
                   "line_numbers": "(opcional) prefixa cada linha com 'N|' — ajuda a compor um `old` exato "
                                   "p/ edit_file (default: desligado)"}
    arg_types = {"offset": "integer", "limit": "integer", "line_numbers": "boolean"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "read_file: 'path' precisa ser uma string não-vazia.", effect=False)
        if _SENSITIVE_PATH.search(rel):                  # INCONDICIONAL (nem yolo): ler credencial do usuário
            return ToolResult(False,                     # é exfiltração, não trabalho. yolo NÃO é porta dos fundos.
                              "arquivo de credencial/segredo (.env/.ssh/.aws/credenciais/OAuth/keychain/*.pem/"
                              f"*.key) — leitura BLOQUEADA (nem yolo passa). Não vasculhe credencial do usuário; "
                              f"se falta uma, PEÇA ao dono pelo canal seguro (ele guarda cifrada no cofre). ({rel})",
                              effect=False)
        remote = getattr(ctx, "remote", None)            # AMBIENTE REMOTO: lê na máquina remota (cat)
        if remote is not None:
            rr = remote.read(rel)
            if rr.returncode != 0:
                from okami.core.redact import redact
                return ToolResult(False, f"[📡 {remote.alias}] não consegui ler '{rel}': "
                                  f"{redact(rr.output).strip()[:300] or 'arquivo não existe / sem permissão'}",
                                  effect=False)
            ctx.read_files.add(rel)                       # grounding p/ um edit_file remoto depois
            return ToolResult(True, rr.output, effect=False)
        from okami.core.file_safety import read_text_capped
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        # erros ACIONÁVEIS (anti-thrash): o modelo chutava caminho e levava OSError cru → re-tentava sem fim.
        if p.is_dir():
            return ToolResult(False, f"'{rel}' é um DIRETÓRIO, não um arquivo — use list_dir('{rel}') p/ ver "
                              "o conteúdo (read_file é só p/ arquivo).", effect=False)
        if not p.exists():
            return ToolResult(False, f"arquivo não existe: {rel} — NÃO chute o caminho; use list_dir p/ navegar "
                              "ou find_files p/ achar pelo nome." + _read_did_you_mean(p, rel), effect=False)
        from okami.core.read_extract import extract_text, is_extractable
        if is_extractable(rel):               # #9: .docx/.xlsx/.ipynb → extrai texto (senão vem binário/lixo)
            text = extract_text(p)
            if text is None:
                return ToolResult(False, f"não consegui extrair texto de {rel} (arquivo corrompido ou vazio?).",
                                  effect=False)
            ctx.read_files.add(rel)
            return ToolResult(True, text, effect=False)
        _bg = _binary_guard(rel, p)           # PNG/áudio/vídeo/objeto → viraria mojibake no contexto: recusa clara
        if _bg is not None:
            return _bg
        try:
            text = read_text_capped(p)        # teto de tamanho → não estoura memória
        except Exception as e:  # noqa: BLE001 — inclui FileTooLarge (msg clara)
            return ToolResult(False, f"erro ao ler {rel}: {e}", effect=False)
        text, _ = _strip_bom(text)            # BOM (se houver) não aparece pro modelo — write/edit restauram
        text = _truncate_long_lines(text)     # per-line cap — 1 linha minificada não floda o contexto
        from okami.core.tools.file_state import record_read
        record_read(ctx, rel, p)              # grounding + baseline de mtime p/ o anti-stale (item 7)
        hint = ""                             # #8 item 7: convenção da subpasta (1× por pasta/turno)
        try:
            from okami.core.subdir_hints import subdir_hint
            hint = subdir_hint(ctx.workspace, p, ctx.hinted_dirs)
        except Exception:  # noqa: BLE001 — hint é best-effort, nunca derruba o read
            hint = ""
        # PAGINAÇÃO (offset/limit por LINHA): recupera o resto de uma saída grande persistida sem
        # trazer o arquivo inteiro. Sem offset/limit → arquivo inteiro (back-compat).
        off = _as_int(args.get("offset"))
        lim = _as_int(args.get("limit"))
        # line_numbers (FIX 3, opt-in — default OFF p/ não mudar o formato existente): prefixa "N|" (formato
        # Hermes) — ajuda o modelo a mirar a linha certa ao compor um `old` exato p/ edit_file.
        numbered = bool(args.get("line_numbers", False))
        if off is None and lim is None:
            if len(text) > 100_000:                   # arquivo gigante sem range → não despeja inteiro no
                nlines = text.count("\n") + 1          # contexto; manda paginar com offset/limit (por LINHA)
                return ToolResult(False, f"'{rel}' é grande ({len(text):,} chars, {nlines:,} linhas) — não "
                                  "leio inteiro de uma vez. Pagine: read_file com offset/limit (por linha), "
                                  "ou use search_files p/ achar o trecho.", effect=False)
            out = _add_line_numbers(text, 1) if numbered else text
            return ToolResult(True, out + hint, effect=False)
        lines = text.splitlines()
        start = max(0, off or 0)
        if start >= len(lines) and lines:
            return ToolResult(True, f"(offset {start} além do fim — o arquivo tem {len(lines)} linha(s))",
                              effect=False)
        end = start + lim if lim is not None else len(lines)
        window = lines[start:end]
        chunk = "\n".join(f"{start + i + 1}|{ln}" for i, ln in enumerate(window)) if numbered \
            else "\n".join(window)
        remaining = len(lines) - end
        if remaining > 0:
            chunk += f"\n\n[… +{remaining} linha(s); continue com offset={end} …]"
        return ToolResult(True, chunk + hint, effect=False)


class WriteFile(Tool):
    name = "write_file"
    description = "Escreve/sobrescreve um arquivo. Para sobrescrever um existente, leia-o antes (grounding)."
    args_schema = {"path": "caminho relativo", "content": "conteúdo completo do arquivo"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:           # path None/tipo-errado → erro limpo (não TypeError)
            return ToolResult(False, "write_file: 'path' precisa ser uma string não-vazia.")
        content = args.get("content", "")
        if not isinstance(content, str):                  # None/bytes/num → coage p/ texto (não crasha o .encode)
            content = "" if content is None else str(content)
        remote = getattr(ctx, "remote", None)            # AMBIENTE REMOTO: escreve na máquina remota (tee atômico)
        if remote is not None:
            if getattr(ctx.sandbox, "mode", "") != "yolo" and _SENSITIVE_PATH.search(rel):
                return ToolResult(False, f"arquivo sensível (.env/.ssh/.aws/credenciais) bloqueado mesmo no "
                                  f"remoto: {rel}. Use o perfil yolo se for de propósito.", effect=False)
            rr = remote.write(rel, content)
            if rr.returncode != 0:
                from okami.core.redact import redact
                return ToolResult(False, f"[📡 {remote.alias}] erro ao escrever '{rel}': "
                                  f"{redact(rr.output).strip()[:300]}", effect=False)
            ctx.read_files.add(rel)
            return ToolResult(True, f"[📡 {remote.alias}] escrito {rel} ({len(content)} chars)", effect=True)
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e))
        # Grounding anti-alucinação (§3.7): não sobrescreve existente não-lido.
        if p.exists() and rel not in ctx.read_files:
            return ToolResult(
                False,
                f"'{rel}' já existe e você não o leu. Use read_file antes de sobrescrever (grounding).",
            )
        from okami.core.tools.file_state import check_stale, record_read
        stale = check_stale(ctx, rel, p)               # item 7: mudou no disco depois da leitura? bloqueia
        if stale:
            return ToolResult(False, stale, effect=False)
        if ctx.checkpoints is not None:                # snapshot do estado ANTERIOR (rede de segurança)
            try:
                ctx.checkpoints.snapshot(rel)
            except Exception:  # noqa: BLE001 — checkpoint é best-effort, nunca bloqueia a escrita
                pass
        before = ""
        existed = p.exists()
        # sniff line-ending/BOM ORIGINAIS antes de qualquer leitura/escrita — write_text_atomic vai
        # sobrescrever o arquivo, então isto tem que rodar ANTES (CRLF/BOM preservation).
        orig_ending = _detect_line_ending(p) if existed else None
        orig_bom = _has_bom_on_disk(p) if existed else False
        if existed:                                     # lint-delta: erro pré-existente não nagueia
            try:
                from okami.core.file_safety import read_text_capped
                before, _ = _strip_bom(read_text_capped(p))
            except Exception:  # noqa: BLE001
                before = ""
        from okami.core.file_safety import FileTooLarge, write_text_atomic
        out_content = content                          # conteúdo em LF/sem BOM (o que o modelo manda) — a
        if orig_ending == "\r\n":                       # versão em disco preserva o line-ending/BOM originais
            out_content = _restore_line_ending(out_content, "\r\n")
        if orig_bom and not out_content.startswith("﻿"):
            out_content = "﻿" + out_content
        try:
            n = write_text_atomic(p, out_content)   # atômico (sem arquivo meia-escrito) + teto de tamanho
        except FileTooLarge as e:
            return ToolResult(False, str(e))
        record_read(ctx, rel, p)  # acabou de escrever → conhece o conteúdo + atualiza baseline anti-stale
        from okami.core.code_lint import lint_delta, semantic_delta  # item 6/16: avisa erro NOVO (não bloqueia)
        from okami.core.code_security import security_warn            # #9: padrão perigoso no que o agente grava
        warn = lint_delta(rel, before, content)
        sem = semantic_delta(ctx.workspace, rel, before, content)    # item 16: diagnóstico semântico (pyright)
        sem2 = _multi_lang_delta(ctx.workspace, rel, before, content)  # #19: outras linguagens (LSP persistente)
        sec = security_warn(rel, content)
        extra = "".join(f"\n{w}" for w in (warn, sem, sem2, sec) if w)
        return ToolResult(True, f"escrito {rel} ({n} chars)" + extra, effect=True)


def _edit_did_you_mean(text: str, old: str, rel: str, *, max_lines: int = 10, max_results: int = 3) -> str:
    """Quando 'old' não casa EXATO, acha até TOP-3 seções mais PARECIDAS no arquivo e devolve snippets p/ o
    modelo copiar o texto literal (paridade Hermes find_closest_lines max_results=3). Tira o agente do loop
    de re-chutar `old` — antes só mostrava 1 candidato; se ele era o errado, o modelo ficava sem opção B/C.
    '' se não houver nada minimamente parecido."""
    import difflib
    old_lines = old.splitlines()
    anchor = next((ln.strip() for ln in old_lines if ln.strip()), "")
    if not anchor:
        return ""
    file_lines = text.splitlines()
    scored = []
    for i, ln in enumerate(file_lines):
        stripped = ln.strip()
        if not stripped:
            continue
        r = difflib.SequenceMatcher(None, anchor, stripped).ratio()
        if r >= 0.55:                                      # mesmo piso de antes — abaixo disso não é "parecido"
            scored.append((r, i))
    if not scored:
        return ""
    scored.sort(key=lambda x: -x[0])
    block_len = max(1, len(old_lines))
    parts, seen_ranges = [], set()
    for r, i in scored:
        if len(parts) >= max_results:
            break
        lo = max(0, i - 2)
        # contexto ATÉ +1 linha depois do bloco (não +2): com +2 o snippet de um candidato podia
        # engolir a PRÓXIMA definição/função do arquivo (achado no teste top-3: janela do 3º
        # candidato vazava pro início de um 4º bloco não-parecido, poluindo o "did you mean").
        hi = min(len(file_lines), i + block_len + 1)
        key = (lo, hi)
        if key in seen_ranges:                              # candidatos vizinhos colapsam na mesma janela
            continue
        seen_ranges.add(key)
        snippet_lines = file_lines[lo:hi][:max_lines]
        numbered = "\n".join(f"{lo + j + 1}: {ln}" for j, ln in enumerate(snippet_lines))
        parts.append(f"~{rel}:{lo + 1} (~{int(r * 100)}%)\n```\n{numbered}\n```")
    if not parts:
        return ""
    header = " Trecho(s) PARECIDO(s)" if len(parts) == 1 else f" {len(parts)} trechos PARECIDOS"
    return (f"{header} — copie o texto EXATO de um deles (espaços/indentação contam):\n"
            + "\n---\n".join(parts) +
            "\nSe nenhum casar, re-leia com read_file, ou reescreva o arquivo com write_file.")


class EditFile(Tool):
    name = "edit_file"
    description = ("Edita um arquivo por substituição EXATA de trecho (old→new) — sem reescrever tudo. "
                   "'old' precisa casar literalmente (espaços/indentação) e ser ÚNICO, ou use replace_all.")
    args_schema = {"path": "caminho relativo", "old": "trecho exato a trocar (literal)",
                   "new": "novo trecho", "replace_all": "(opcional) trocar todas as ocorrências"}
    arg_types = {"replace_all": "boolean"}   # nativo manda "false" (string) → bool("false") é True (bug) sem coerção
    required = ("path", "old")

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel.strip():   # modelo fraco manda {"path": null/123} → erro LIMPO
            return ToolResult(False, "edit_file: 'path' precisa ser uma string não-vazia.", effect=False)
        old = args.get("old", "")
        new = args.get("new", "")
        replace_all = bool(args.get("replace_all", False))
        if not old:
            return ToolResult(False, "edit_file exige 'old' (trecho a substituir) não-vazio.")
        remote = getattr(ctx, "remote", None)            # AMBIENTE REMOTO: lê→substitui→escreve na remota
        if remote is not None:
            if getattr(ctx.sandbox, "mode", "") != "yolo" and _SENSITIVE_PATH.search(rel):
                return ToolResult(False, f"arquivo sensível bloqueado mesmo no remoto: {rel}.", effect=False)
            from okami.core.redact import redact
            rr = remote.read(rel)
            if rr.returncode != 0:
                return ToolResult(False, f"[📡 {remote.alias}] não consegui ler '{rel}' p/ editar: "
                                  f"{redact(rr.output).strip()[:200] or 'não existe?'}", effect=False)
            text = rr.output
            count = text.count(old)
            if count == 0:
                return ToolResult(False, f"[📡 {remote.alias}] trecho não encontrado em {rel} — precisa ser "
                                  "EXATO (incl. espaços)." + _edit_did_you_mean(text, old, rel), effect=False)
            if count > 1 and not replace_all:
                return ToolResult(False, f"[📡 {remote.alias}] 'old' aparece {count}× em {rel} — torne-o único "
                                  "ou passe replace_all=true.", effect=False)
            new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
            wr = remote.write(rel, new_text)
            if wr.returncode != 0:
                return ToolResult(False, f"[📡 {remote.alias}] erro ao escrever '{rel}': "
                                  f"{redact(wr.output).strip()[:200]}", effect=False)
            n = count if replace_all else 1
            return ToolResult(True, f"[📡 {remote.alias}] editado {rel} ({n} substituiç"
                              f"{'ões' if n > 1 else 'ão'})", effect=True)
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e))
        if not p.exists():
            return ToolResult(False, f"'{rel}' não existe — use write_file para criar.")
        # Grounding (paridade Hermes): ler-antes-de-editar vira AVISO, não bloqueio. O `old` PRECISA casar
        # conteúdo real (o match já É o grounding — não dá pra alucinar uma edição), então recusar a edição
        # só forçava um read→edit em 2 passos + thrash de recuperação. Hermes só avisa e segue.
        ground_warn = ("" if rel in ctx.read_files else
                       f"⚠ editou {rel} sem ler antes — o trecho casou (ok), mas reler evita editar a versão errada.")
        from okami.core.tools.file_state import check_stale, record_read
        stale = check_stale(ctx, rel, p)               # item 7: mudou no disco depois da leitura? bloqueia
        if stale:
            return ToolResult(False, stale, effect=False)
        from okami.core.file_safety import MAX_WRITE_BYTES, read_text_capped, write_text_atomic
        # sniff line-ending/BOM ORIGINAIS antes da leitura (write_text_atomic vai sobrescrever depois) —
        # CRLF/BOM preservation: sem isto, o 1º edit num arquivo Windows normaliza silenciosamente pra LF.
        orig_ending = _detect_line_ending(p)
        orig_bom = _has_bom_on_disk(p)
        try:
            # P1 do audit 2026-06-07: EditFile usava MAX_READ_BYTES (5MB) e quebrava com
            # mensagem confusa ("use run_shell p/ fatiar") mesmo quando o `old` cabia nos
            # primeiros MB. Agora usa o mesmo teto da escrita (10MB) — o `old` que cabe em
            # 10MB é editável; o que não cabe, retorna erro claro com o limite.
            text = read_text_capped(p, limit=MAX_WRITE_BYTES)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro ao ler {rel}: {e}")
        text, _ = _strip_bom(text)   # o `old` do modelo vem de um read_file já sem BOM — compara igual
        # Cadeia de matching fuzzy (paridade Hermes, 9 estratégias — fuzzy_match.py): tenta exato primeiro,
        # depois vai afrouxando (whitespace/indentação/escape/unicode/âncora/similaridade), parando na
        # PRIMEIRA que casar de forma ÚNICA. Substitui o antigo fallback único (_fuzzy_replace).
        from okami.core.tools.fuzzy_match import fuzzy_find_and_replace
        new_text, n, strategy, err = fuzzy_find_and_replace(text, old, new, replace_all=replace_all)
        if err is not None:
            if err.startswith("Found "):                # >1 match no MESMO nível de estratégia → não escolhe sozinho
                import re as _re
                m = _re.search(r"Found (\d+) matches", err)
                cnt = m.group(1) if m else "vários"
                return ToolResult(False, f"'old' aparece {cnt}× em {rel} — torne-o único (mais contexto) "
                                         "ou passe replace_all=true.")
            return ToolResult(False, f"trecho não encontrado em {rel} — precisa ser EXATO (incl. espaços)."
                              + _edit_did_you_mean(text, old, rel), effect=False)
        if ctx.checkpoints is not None:                # snapshot antes (rede de segurança / rollback)
            try:
                ctx.checkpoints.snapshot(rel)
            except Exception:  # noqa: BLE001
                pass
        out_text = new_text                   # new_text é LF/sem BOM — restaura o original antes de gravar
        if orig_ending == "\r\n":
            out_text = _restore_line_ending(out_text, "\r\n")
        if orig_bom and not out_text.startswith("﻿"):
            out_text = "﻿" + out_text
        write_text_atomic(p, out_text)        # escrita atômica (rede de segurança)
        record_read(ctx, rel, p)              # conhece o conteúdo + atualiza baseline anti-stale
        from okami.core.code_lint import lint_delta, semantic_delta  # item 6/16: erro NOVO pela edição
        from okami.core.code_security import security_warn            # #9: padrão perigoso introduzido
        warn = lint_delta(rel, text, new_text)
        sem = semantic_delta(ctx.workspace, rel, text, new_text)     # item 16: diagnóstico semântico (pyright)
        sem2 = _multi_lang_delta(ctx.workspace, rel, text, new_text)  # #19: outras linguagens (LSP persistente)
        sec = security_warn(rel, new_text)
        line_no = _first_changed_line(text, old, new)                # item 8: nº da 1ª linha mudada
        diff = _short_diff(text, new_text)                           # item 8: diff unified curto (capado)
        # calibração (§TASK item 4): mostra qual estratégia casou quando não foi exata — ajuda o modelo a
        # perceber que o `old` que ele mandou não era byte-a-byte igual ao arquivo.
        strat_note = f" (match: {strategy})" if strategy and strategy != "exact" else ""
        head = f"editado {rel}:{line_no} ({n} substituiç{'ões' if n > 1 else 'ão'}){strat_note}"
        extra = "".join(f"\n{w}" for w in (ground_warn, warn, sem, sem2, sec) if w)
        return ToolResult(True, head + (f"\n{diff}" if diff else "") + extra, effect=True)


class ListDir(Tool):
    name = "list_dir"
    description = "Lista arquivos/pastas de um diretório do workspace."
    args_schema = {"path": "caminho relativo (use '.' para a raiz)"}

    def run(self, args, ctx):
        rel = args.get("path", ".")
        remote = getattr(ctx, "remote", None)            # AMBIENTE REMOTO: lista o diretório remoto (ls)
        if remote is not None:
            rr = remote.list(rel)
            if rr.returncode != 0:
                from okami.core.redact import redact
                return ToolResult(False, f"[📡 {remote.alias}] erro ao listar '{rel}': "
                                  f"{redact(rr.output).strip()[:200]}", effect=False)
            return ToolResult(True, f"[📡 {remote.alias}]\n{rr.output.strip() or '(vazio)'}", effect=False)
        try:
            p = _safe_path(ctx, rel)
            # incidente 2026-07-08: read_file já barra o CONTEÚDO de credencial, mas list_dir ENUMERAVA o
            # nome (client_secret_*.json, credentials.json, .aws…) → o agente sabia que existia e partia p/
            # o yolo. Some da listagem também (INCONDICIONAL, nem yolo): não existe p/ o agente.
            entries = sorted(e.name + ("/" if e.is_dir() else "")
                             for e in p.iterdir() if not _SENSITIVE_PATH.search(str(p / e.name)))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro ao listar {rel}: {e}")
        return ToolResult(True, "\n".join(entries) or "(vazio)", effect=False)


def _norm_name(s: str) -> str:
    """Normaliza p/ busca fuzzy: só alfanum, minúsculo (hífen/underscore/espaço/caso somem).
    'Okami-Agent' == 'okami_agent' == 'okamiagent'."""
    return "".join(c for c in s.lower() if c.isalnum())


class FindFiles(Tool):
    name = "find_files"
    description = ("Acha arquivos/pastas por nome no workspace — case-INSENSITIVE e fuzzy (acha "
                   "'okami-agent' mesmo a pasta sendo 'Okami-Agent'). Prefira a isto em vez de `find` "
                   "quando o nome pode variar em caso/hífen/underscore.")
    args_schema = {"query": "parte do nome (caso/hífen/underscore/espaço são ignorados)"}
    required = ("query",)
    _SKIP = {".git", "__pycache__", ".venv", "node_modules", ".okami", ".pytest_cache", "dist"}

    def run(self, args, ctx):
        raw = args.get("query")
        q = _norm_name(raw if isinstance(raw, str) else ("" if raw is None else str(raw)))
        if not q:
            return ToolResult(False, "find_files exige 'query' não-vazio.")
        hits = []
        for p in ctx.workspace.rglob("*"):
            rel = p.relative_to(ctx.workspace)               # _SKIP só vale DENTRO do workspace — senão um
            if any(part in self._SKIP for part in rel.parts):  # ancestral skip-listed (o agente roda sob
                continue                                     # ~/.okami/…) zerava TODA busca (find_files cego)
            if _SENSITIVE_PATH.search(str(p)):               # incidente 2026-07-08: não ENUMERA credencial
                continue                                     # (read_file já barra o conteúdo; aqui some o nome)
            if q in _norm_name(p.name):
                hits.append(str(rel) + ("/" if p.is_dir() else ""))
                if len(hits) >= 60:
                    break
        return ToolResult(True, "\n".join(sorted(hits)) or f"(nada casou com '{args['query']}')", effect=False)


def _fs_pair(ctx, args):
    """Resolve src/dst com jail + denylist de segredo. Retorna (src, dst) ou ToolResult de erro."""
    for k in ("src", "dst"):
        v = args.get(k)
        if not isinstance(v, str) or not v:
            return ToolResult(False, f"'{k}' precisa ser uma string não-vazia.", effect=False)
        if _SENSITIVE_PATH.search(v):                    # INCONDICIONAL (nem yolo) — igual read_file
            return ToolResult(False, "caminho de credencial/segredo (.env/.ssh/.aws/credenciais/OAuth/keychain) "
                              f"— BLOQUEADO (nem yolo passa). Peça a credencial ao dono pelo canal seguro. ({v})",
                              effect=False)
    try:
        return _safe_path(ctx, args["src"]), _safe_path(ctx, args["dst"])
    except ValueError as e:
        return ToolResult(False, str(e), effect=False)


class MakeDir(Tool):
    name = "make_dir"
    description = "Cria um diretório (com os pais, tipo mkdir -p). Já existir não é erro."
    args_schema = {"path": "caminho do diretório a criar"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "make_dir: 'path' precisa ser uma string não-vazia.", effect=False)
        try:
            p = _safe_path(ctx, rel)
            p.mkdir(parents=True, exist_ok=True)
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        except OSError as e:
            return ToolResult(False, f"erro ao criar {rel}: {e}", effect=False)
        return ToolResult(True, f"diretório pronto: {rel}", effect=True)


class MovePath(Tool):
    name = "move_path"
    description = ("Move/renomeia arquivo OU pasta (cria os diretórios-pai do destino). Funciona com "
                   "binário e pasta inteira — é o jeito certo de ORGANIZAR arquivos (não use "
                   "read+write). Recusa sobrescrever destino existente.")
    args_schema = {"src": "caminho de origem (arquivo ou pasta)",
                   "dst": "caminho de destino (novo nome/local)"}
    required = ("src", "dst")

    def run(self, args, ctx):
        pair = _fs_pair(ctx, args)
        if isinstance(pair, ToolResult):
            return pair
        src, dst = pair
        if not src.exists():
            return ToolResult(False, f"origem não existe: {args['src']} — use list_dir p/ conferir o nome.",
                              effect=False)
        if dst.exists():
            return ToolResult(False, f"destino já existe: {args['dst']} — escolha outro nome (move_path "
                              "não sobrescreve).", effect=False)
        import shutil
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as e:
            return ToolResult(False, f"erro ao mover: {e}", effect=False)
        return ToolResult(True, f"movido: {args['src']} → {args['dst']}", effect=True)


class CopyPath(Tool):
    name = "copy_path"
    description = "Copia arquivo OU pasta (recursivo; cria os pais do destino). Recusa sobrescrever."
    args_schema = {"src": "caminho de origem", "dst": "caminho de destino"}
    required = ("src", "dst")

    def run(self, args, ctx):
        pair = _fs_pair(ctx, args)
        if isinstance(pair, ToolResult):
            return pair
        src, dst = pair
        if not src.exists():
            return ToolResult(False, f"origem não existe: {args['src']}", effect=False)
        if dst.exists():
            return ToolResult(False, f"destino já existe: {args['dst']} — copy_path não sobrescreve.",
                              effect=False)
        import shutil
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError as e:
            return ToolResult(False, f"erro ao copiar: {e}", effect=False)
        return ToolResult(True, f"copiado: {args['src']} → {args['dst']}", effect=True)


class DeletePath(Tool):
    name = "delete_path"
    description = ("Remove arquivo/pasta de forma REVERSÍVEL: move pra lixeira do Okami "
                   "(~/.okami/trash) em vez de apagar de verdade. Nada é destruído.")
    args_schema = {"path": "arquivo ou pasta a remover (vai pra lixeira)"}
    required = ("path",)

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "delete_path: 'path' precisa ser uma string não-vazia.", effect=False)
        if getattr(ctx.sandbox, "mode", "") != "yolo" and _SENSITIVE_PATH.search(rel):
            return ToolResult(False, "caminho sensível (.env/.ssh/.aws/credenciais/*.pem/*.key) — "
                              f"bloqueado. ({rel})", effect=False)
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        if not p.exists():
            return ToolResult(False, f"não existe: {rel}", effect=False)
        import shutil
        import time
        from okami.home import okami_home
        trash = okami_home() / "trash" / time.strftime("%Y%m%d-%H%M%S")
        dst = trash / p.name
        try:
            trash.mkdir(parents=True, exist_ok=True)
            if dst.exists():                                   # mesmo nome no mesmo segundo → sufixo
                dst = trash / f"{p.name}.{len(list(trash.iterdir()))}"
            shutil.move(str(p), str(dst))
        except OSError as e:
            return ToolResult(False, f"erro ao mover pra lixeira: {e}", effect=False)
        return ToolResult(True, f"movido pra lixeira: {rel} → {dst} (reversível)", effect=True)


# Utilitários que usam exit≠0 como SINAL, não erro (paridade Hermes _interpret_exit_code): programa →
# (código benigno, nota). Tratar como falha fazia o agente "investigar" um não-erro e alimentava o
# circuit-breaker do harness → travava sem seguir em frente.
_BENIGN_EXIT: dict[str, tuple[int, str]] = {
    "grep": (1, "nenhuma linha casou — NÃO é erro"),
    "egrep": (1, "nenhuma linha casou — NÃO é erro"),
    "fgrep": (1, "nenhuma linha casou — NÃO é erro"),
    "rg": (1, "nenhuma linha casou — NÃO é erro"),
    "diff": (1, "os arquivos diferem — esperado, NÃO é erro"),
    "cmp": (1, "os arquivos diferem — esperado, NÃO é erro"),
    "test": (1, "condição falsa — NÃO é erro"),
    "[": (1, "condição falsa — NÃO é erro"),
}


def interpret_exit_code(cmd: str, returncode: int) -> tuple[bool, str]:
    """Semântica de exit-code por comando. Devolve (ok, nota). Default: ok = (returncode == 0). Para
    grep/rg/diff/test o código benigno conhecido vira ok=True com uma nota — assim o modelo não confunde
    'nada casou' com falha. Erro de VERDADE (grep exit 2, etc.) segue ok=False."""
    if returncode == 0:
        return True, ""
    seg = (cmd or "").split("|")[-1].strip()                  # exit do pipeline = do ÚLTIMO comando
    prog = ""
    for t in seg.split():                                     # pula env-prefixos (VAR=val) e wrappers
        if ("=" in t and not t.startswith(("-", "/"))) or t in ("sudo", "time", "command", "nice", "nohup"):
            continue
        prog = t
        break
    prog = prog.rsplit("/", 1)[-1].strip("'\"")               # basename, sem aspas
    benign = _BENIGN_EXIT.get(prog)
    if benign and returncode == benign[0]:
        return True, benign[1]
    return False, ""


class RunShell(Tool):
    name = "run_shell"
    description = ("Executa um comando de shell no workspace, sob sandbox (timeout, teto de saída, env "
                   "sanitizado; isolamento real com backend docker). Em perfil read-only, comando que "
                   "altera estado é bloqueado. Comando demorado: passe timeout=N (máx 1800s) ou, p/ algo "
                   "realmente longo (servidor/build), use process_start (background, sem teto). cwd e "
                   "env (export) PERSISTEM entre chamadas desta MESMA conversa (backend local) — `cd sub` "
                   "numa chamada vale na próxima, `export FOO=bar` também. `cd` continua PRESO ao "
                   "workspace (cd pra fora é recusado, cwd não muda). Backend docker efêmero (sem "
                   "reuse_container) e ambiente remoto: sem essa persistência — encadeie com `&&` "
                   "(ex.: `cd sub && npm test`) ou use caminho absoluto nesses casos.")
    args_schema = {"cmd": "comando a executar",
                   "timeout": "(opc) segundos até cortar o comando — default 120, máx 1800"}
    arg_types = {"timeout": "integer"}
    required = ("cmd",)
    _MAX_TIMEOUT = 1800           # 30min de teto p/ UM comando — acima disso é trabalho de background (process_start)

    def run(self, args, ctx):
        import dataclasses
        from okami.core.sandbox import default_policy, run_sandboxed
        cmd = args.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():   # modelo fraco manda {"cmd": null/123/[…]} → erro LIMPO
            return ToolResult(False, "run_shell: 'cmd' precisa ser uma string não-vazia.", effect=False)
        eff = shell_has_effect(cmd)   # read-only (ls/grep/cat…) → effect=False (não engana o watchdog)
        policy = ctx.sandbox or default_policy()
        # timeout POR-CHAMADA: comando sabidamente demorado (teste/build grande, transformar arquivo enorme)
        # pode pedir mais tempo sem mexer no default global. Clamp p/ não virar "trava pra sempre".
        to = args.get("timeout")
        if to is not None:
            try:
                policy = dataclasses.replace(policy, timeout=max(1, min(int(to), self._MAX_TIMEOUT)))
            except (TypeError, ValueError):
                pass                                              # timeout inválido → ignora, usa o da policy
        mode = getattr(policy, "mode", "")
        from okami.core import approval as _ap
        _hl = _ap.detect_hardline(cmd)
        if _hl:                                                  # HARDLINE (Hermes): bloqueio INCONDICIONAL —
            return ToolResult(False, f"🛑 BLOQUEADO (hardline): {_hl}. Comando catastrófico sem uso "  # nem /yolo passa
                              f"legítimo — recusado em QUALQUER modo. ({cmd[:80]})", effect=False)
        if mode == "read-only" and eff:                          # defesa em profundidade (perfil)
            return ToolResult(False, f"sandbox read-only: comando que altera estado bloqueado ({cmd[:80]})",
                              effect=False)
        if _SENSITIVE_PATH.search(cmd):                          # INCONDICIONAL (nem yolo) — exfil não é trabalho
            return ToolResult(False, "sandbox: comando toca caminho de credencial/segredo (.env/.ssh/.aws/"
                              "credenciais/OAuth/keychain/*.pem/*.key) — BLOQUEADO (nem yolo passa). Não leia "
                              f"credencial do usuário; peça ao dono pelo canal seguro. ({cmd[:80]})",
                              effect=False)
        if mode != "yolo":                                       # #12: Tirith — scan de CONTEÚDO (homograph,
            from okami.core.tirith import scan_command           # pipe-to-interpreter, terminal-injection) que o
            _tir = scan_command(cmd, cfg=getattr(ctx, "cfg", None))  # regex não pega. Inerte sem o binário.
            if _tir.get("available") and _tir.get("verdict") == "block":
                _ids = ", ".join(str(f.get("id", "?")) for f in _tir.get("findings", [])[:3]) or "ameaça"
                return ToolResult(False, f"🛡 BLOQUEADO (tirith): ameaça de conteúdo no comando ({_ids}). "
                                  f"Use o perfil yolo se for de propósito. ({cmd[:80]})", effect=False)
        from okami.core.redact import redact, strip_ansi   # token impresso na saída (gh auth/build log) NÃO pode
        remote = getattr(ctx, "remote", None)           # AMBIENTE REMOTO: roda LÁ, não no sandbox local
        if remote is not None:                          # (as guardas hardline/read-only/sensível JÁ rodaram acima)
            rr = remote.run(cmd, timeout=policy.timeout)
            ok, note = interpret_exit_code(cmd, rr.returncode)
            out = f"[📡 {getattr(remote, 'alias', 'remoto')}] exit={rr.returncode}\n{redact(strip_ansi(rr.output))}"
            if note:
                out += f"\n[{note}]"
            return ToolResult(ok, out, effect=eff)
        session_key = str(getattr(ctx, "chat_id", "") or id(ctx))   # #stateful-shell: conversa (chat_id)
        # ou, sem chat_id (CLI puro), a identidade do próprio ToolContext — persiste dentro do MESMO
        # Harness/processo (cd/export sobrevivem entre chamadas do turno/conversa), mas NUNCA vaza
        # entre ctx diferentes (dois Harness/testes não compartilham cwd).
        res = run_sandboxed(cmd, ctx.workspace, policy, session_key=session_key)
        ok, note = interpret_exit_code(cmd, res.returncode)      # grep/rg/diff/test exit≠0 ≠ falha real
        out = f"exit={res.returncode}\n{redact(strip_ansi(res.output))}"   # strip_ansi→redact (igual ao bg log)
        if note:
            out += f"\n[{note}]"
        if getattr(res, "timed_out", False):                     # cortou no teto → ensina a recuperar (não é "falha real")
            out += (f"\n[o comando passou de {policy.timeout}s e foi cortado. Se é legítimo e demora mesmo: "
                    f"rode de novo com timeout=N (máx {self._MAX_TIMEOUT}), ou use process_start p/ rodar "
                    "em background sem teto e acompanhar com process_poll/process_log.]")
        return ToolResult(ok, out, effect=eff)
