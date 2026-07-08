"""search_files — busca por CONTEÚDO no workspace (pesquisa #6 item 2).

O find_files busca por NOME; este busca regex no CONTEÚDO (o que o grep/rg fazem). Fast-path: quando
o binário `rg` (ripgrep) está no PATH, ele enumera os arquivos com match (respeitando .gitignore,
pulando binário/.git sozinho, MUITO mais rápido que os.walk puro num repo grande) — só a ENUMERAÇÃO é
delegada a ele; a extração de linha/contexto/redação continua em Python p/ a saída ficar
byte-idêntica ao fallback. Sem `rg` (ou se a regex não é compatível com o motor dele — backreference/
lookaround), cai no motor 100% Python: jailed ao workspace, pula .git/.venv/binário, modos
content/files/count, filtro glob, contexto -A/-B, paginação, case-insensitive. Redige segredo no
match (igual run_shell).
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

from okami.core.tools.base import Tool, ToolResult

_SKIP = {".git", "__pycache__", ".venv", "node_modules", ".okami", ".pytest_cache", "dist",
         ".mypy_cache", ".ruff_cache", "build", ".idea", ".vscode", ".uv-cache"}
_MAX_MATCHES = 200            # teto de matches devolvidos (paginável por offset)
_MAX_FILE_BYTES = 2_000_000   # arquivo maior que isto não é varrido (provável dado/binário)
_RG_TIMEOUT = 30.0


def _rg_candidate_files(root: Path, pattern: str, ignore_case: bool, glob: str = "*") -> list[Path] | None:
    """Lista de arquivos com pelo menos 1 match via `rg --files-with-matches` (respeita .gitignore
    sozinho — não precisa do _SKIP p/ isso, mas ele é aplicado de novo no caller como cinto+suspensório).
    None = `rg` ausente do PATH, timeout, ou regex incompatível com o motor dele (ex.: backreference/
    lookaround só existem em Python re) — o CALLER cai no motor puro-Python (mesmo resultado, só mais
    lento). Lazy-dep no estilo das outras tools (websearch.check etc): nunca quebra, só degrada."""
    rg = shutil.which("rg")
    if not rg:
        return None
    cmd = [rg, "--files-with-matches", "--no-messages", "-e", pattern]
    if ignore_case:
        cmd.append("--ignore-case")
    if glob and glob != "*":                  # filtro de nome já na enumeração — menos I/O (Python refiltra igual)
        cmd += ["--glob", glob]
    cmd.append(str(root))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_RG_TIMEOUT)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):     # 0 = achou, 1 = rg "sem match nenhum" (não é erro); outro = regex/erro
        return None
    return [Path(line) for line in proc.stdout.splitlines() if line.strip()]


def _as_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


class SearchFiles(Tool):
    name = "search_files"
    description = ("Busca no workspace — é o grep+find do agente. target=content (regex no CONTEÚDO, default) "
                   "OU target=files (acha por NOME de arquivo, fuzzy: caso/hífen/underscore). Opcional: glob "
                   "(ex.: '*.py'), context (linhas ao redor), ignore_case, offset (paginar). É a ÚNICA tool "
                   "de busca de que você precisa.")
    args_schema = {"query": "regex (target=content) ou parte do nome (target=files)",
                   "target": "(opc) content (grep, default) | files (busca por nome)",
                   "path": "(opc) subdir (default raiz)",
                   "glob": "(opc) filtro de nome ex.: *.py", "mode": "(opc) content|files|count",
                   "context": "(opc) nº de linhas ao redor de cada match", "ignore_case": "(opc) true/false",
                   "offset": "(opc) pular N matches (paginação)"}
    required = ("query",)
    arg_types = {"context": "integer", "ignore_case": "boolean", "offset": "integer"}
    # enum trava o domínio de valor no schema NATIVO — sem isto o modelo já chutou "conteudo"/"name"
    # em vez de "content"/"files" (auditoria 2026-07). default espelha o comportamento real do run().
    arg_constraints = {
        "target": {"enum": ["content", "files"]},
        "mode": {"enum": ["content", "files", "count"], "default": "content"},
        "context": {"minimum": 0},
        "offset": {"minimum": 0},
    }

    def run(self, args, ctx):
        from okami.core.redact import redact
        if (args.get("target") or "").lower() == "files":   # paridade Hermes (search_files target=files):
            from okami.core.tools.files import FindFiles     # busca por NOME → delega ao find_files (fuzzy)
            return FindFiles().run({"query": args.get("query")}, ctx)
        q = args.get("query")
        if not isinstance(q, str) or not q:
            return ToolResult(False, "search_files: 'query' precisa ser uma string não-vazia.", effect=False)
        flags = re.IGNORECASE if args.get("ignore_case") else 0
        try:
            rx = re.compile(q, flags)
        except re.error as e:
            return ToolResult(False, f"regex inválido: {e}. Escape metacaracteres ou simplifique o padrão.",
                              effect=False)
        try:
            root = _resolve_root(ctx, args.get("path"))
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        glob = args.get("glob") or "*"
        mode = (args.get("mode") or "content").lower()
        ctx_n = max(0, _as_int(args.get("context"), 0) or 0)
        offset = max(0, _as_int(args.get("offset"), 0) or 0)

        ws_root = Path(ctx.workspace).resolve()      # rglob devolve absoluto → relative_to precisa do resolvido
        # incidente 2026-07-08: grep NUNCA varre arquivo de credencial — senão o próprio match VAZA o segredo
        # no resultado (pior que enumerar). INCONDICIONAL (nem yolo), nos dois caminhos (rg e puro-Python).
        from okami.core.tools.base import _SENSITIVE_PATH
        _ok = lambda p: not _SENSITIVE_PATH.search(str(p))
        candidates = _rg_candidate_files(root, q, bool(args.get("ignore_case")), glob)
        if candidates is not None:                    # fast-path rg: só os arquivos que JÁ têm match
            paths = sorted({p for p in candidates if p.is_file() and _ok(p)})
        else:                                         # fallback puro-Python: todo arquivo sob root
            paths = sorted(p for p in root.rglob("*") if not p.is_dir() and _ok(p))
        per_file: dict[str, int] = {}
        blocks: list[str] = []
        seen = 0
        truncated = False
        for p in paths:
            try:
                rel_to_root = p.relative_to(root)
            except ValueError:                        # rg devolveu path fora de root (não deveria) → ignora
                continue
            if any(part in _SKIP for part in rel_to_root.parts):
                continue
            if not fnmatch.fnmatch(p.name, glob):
                continue
            try:
                if p.stat().st_size > _MAX_FILE_BYTES:
                    continue
                raw = p.read_bytes()
            except OSError:
                continue
            if _is_binary(raw[:1024]):
                continue
            lines = raw.decode("utf-8", "ignore").splitlines()
            try:
                rel = str(p.relative_to(ws_root))
            except ValueError:                       # fora do workspace (open_fs/allow_paths) → caminho absoluto
                rel = str(p)
            for i, line in enumerate(lines):
                if not rx.search(line):
                    continue
                per_file[rel] = per_file.get(rel, 0) + 1
                seen += 1
                if seen <= offset:
                    continue
                if mode == "content" and len(blocks) < _MAX_MATCHES:
                    if ctx_n:
                        lo, hi = max(0, i - ctx_n), min(len(lines), i + ctx_n + 1)
                        chunk = "\n".join(f"{rel}:{j + 1}: {redact(lines[j])}" for j in range(lo, hi))
                        blocks.append(chunk)
                    else:
                        blocks.append(f"{rel}:{i + 1}: {redact(line)}")
                elif mode == "content":
                    truncated = True
        if not per_file:
            return ToolResult(True, f"(nada casou com '{q}')", effect=False)
        if mode == "count":
            body = "\n".join(f"{f}: {n}" for f, n in sorted(per_file.items()))
            return ToolResult(True, f"{len(per_file)} arquivo(s) com match:\n{body}", effect=False)
        if mode == "files":
            return ToolResult(True, "\n".join(sorted(per_file)), effect=False)
        out = "\n".join(blocks)
        if truncated:
            out += f"\n[… mais matches; {len(blocks)} mostrados, continue com offset={offset + len(blocks)}]"
        return ToolResult(True, out, effect=False)


def _resolve_root(ctx, sub: str | None) -> Path:
    """Subdiretório de busca, dentro do jail. Default = raiz do workspace."""
    from okami.core.file_safety import safe_path
    p = safe_path(ctx.workspace, sub or ".", open_fs=getattr(ctx, "open_fs", False),
                  allow_paths=getattr(ctx, "allow_paths", None))
    return p if p.is_dir() else ctx.workspace
