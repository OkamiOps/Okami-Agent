"""apply_patch — modo PATCH multi-arquivo (pesquisa #5 item 20; V4A do Hermes/OpenAI apply_patch).

Um envelope só Update/Add/Delete/Move N arquivos com hunks de contexto e matching FUZZY (3 níveis:
exato → ignora espaço no fim → ignora indentação). Atômico ENTRE arquivos: TUDO é validado e
computado antes de qualquer escrita — um hunk inválido aborta o patch inteiro sem tocar nada.
Mesmas redes do edit_file/write_file: jail de workspace, grounding (Update exige leitura prévia),
caminho sensível bloqueado, checkpoint antes de escrever, escrita atômica, delete via lixeira.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from okami.core.tools.base import _SENSITIVE_PATH, Tool, ToolResult, _safe_path

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_HEADER = re.compile(r"^\*\*\* (Update|Add|Delete) File: (.+)$")
_MOVE = re.compile(r"^\*\*\* Move to: (.+)$")


class PatchError(ValueError):
    """Patch malformado/inaplicável — a mensagem ENSINA o formato (vai pro modelo re-tentar)."""


@dataclass
class PatchOp:
    kind: str                                  # update | add | delete
    path: str
    move_to: str | None = None
    hunks: list[list[tuple[str, str]]] = field(default_factory=list)   # [(tag ' '/'-'/'+', linha)]


def parse_patch(text: str) -> list[PatchOp]:
    """Parseia o envelope V4A. Levanta PatchError com mensagem que ensina o formato."""
    lines = (text or "").splitlines()
    try:
        start = lines.index(_BEGIN)
        end = lines.index(_END)
    except ValueError:
        raise PatchError(
            "envelope ausente: o patch PRECISA começar com '*** Begin Patch' e terminar com "
            "'*** End Patch'. Dentro: '*** Update File: <path>' (hunks com linhas ' ' contexto / "
            "'-' remove / '+' adiciona), '*** Add File: <path>' (linhas '+'), "
            "'*** Delete File: <path>', e opcional '*** Move to: <path>' após o Update.") from None
    ops: list[PatchOp] = []
    cur: PatchOp | None = None
    for raw in lines[start + 1:end]:
        m = _HEADER.match(raw)
        if m:
            cur = PatchOp(m.group(1).lower(), m.group(2).strip())
            ops.append(cur)
            continue
        mv = _MOVE.match(raw)
        if mv:
            if cur is None or cur.kind != "update":
                raise PatchError("'*** Move to:' só vale logo após um '*** Update File:'.")
            cur.move_to = mv.group(1).strip()
            continue
        if cur is None:
            if raw.strip():
                raise PatchError(f"linha fora de qualquer arquivo: {raw[:60]!r} — comece com "
                                 "'*** Update/Add/Delete File: <path>'.")
            continue
        if raw.startswith("@@"):
            cur.hunks.append([])                       # novo hunk; o locator (@@ def foo) é só dica
            continue
        if raw[:1] in (" ", "-", "+"):
            if not cur.hunks:
                cur.hunks.append([])
            cur.hunks[-1].append((raw[0], raw[1:]))
            continue
        if not raw.strip():
            if cur.hunks:                              # linha vazia DENTRO de hunk = contexto vazio
                cur.hunks[-1].append((" ", ""))
            continue
        raise PatchError(f"linha inválida num hunk: {raw[:60]!r} — prefixe com ' ' (contexto), "
                         "'-' (remove) ou '+' (adiciona).")
    if not ops:
        raise PatchError("patch vazio: nenhum '*** Update/Add/Delete File:' dentro do envelope.")
    for op in ops:
        if op.kind == "update" and not any(h for h in op.hunks):
            raise PatchError(f"Update File '{op.path}' sem hunk — inclua as linhas -/+ com contexto.")
        if op.kind == "add" and not any(t == "+" for h in op.hunks for t, _ in h):
            raise PatchError(f"Add File '{op.path}' sem conteúdo — linhas com prefixo '+'.")
    return ops


_AMBIGUOUS = -2            # contexto casa em VÁRIOS lugares no nível fuzzy → recusa (não escolhe sozinho)


def _find_block(haystack: list[str], needle: list[str], start: int) -> int:
    """Posição do bloco `needle` em `haystack`. EXATO primeiro (a partir de `start`, depois do começo —
    tolera hunk fora de ordem). Sem exato, FUZZY (rstrip → strip) mas SÓ se o match for ÚNICO no arquivo
    inteiro: fuzzy ambíguo casaria no bloco ERRADO e corromperia em silêncio (bug do review). Retorna o
    índice, -1 (não achou) ou _AMBIGUOUS (fuzzy casa em >1 lugar → caller pede mais contexto)."""
    if not needle:
        return start
    span = len(haystack) - len(needle) + 1
    if span <= 0:
        return -1
    for base in (start, 0):                            # exato: à frente do ponto atual, senão do começo
        for i in range(base, span):
            if haystack[i:i + len(needle)] == needle:
                return i
    for norm in (str.rstrip, str.strip):               # fuzzy: divergência de whitespace → exige UNICIDADE
        n = [norm(x) for x in needle]
        matches = [i for i in range(span) if [norm(x) for x in haystack[i:i + len(needle)]] == n]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return _AMBIGUOUS
    return -1


def apply_hunks(text: str, hunks: list[list[tuple[str, str]]], path: str) -> str:
    """Aplica os hunks SEQUENCIALMENTE (busca avança — hunks na ordem do arquivo)."""
    lines = text.splitlines()
    pos = 0
    for n, hunk in enumerate(h for h in hunks if h):
        old = [line for tag, line in hunk if tag in (" ", "-")]
        new = [line for tag, line in hunk if tag in (" ", "+")]
        i = _find_block(lines, old, pos)
        if i == _AMBIGUOUS:
            ctx = "\n".join(old[:3])
            raise PatchError(f"hunk {n + 1} de '{path}': o contexto casa em VÁRIOS lugares (ignorando "
                             f"espaços) — ambíguo:\n{ctx}\n— inclua MAIS linhas de contexto (' ') p/ "
                             "tornar o trecho único.")
        if i < 0:
            ctx = "\n".join(old[:3])
            raise PatchError(f"hunk {n + 1} de '{path}': contexto não encontrado no arquivo:\n{ctx}\n"
                             "— copie as linhas EXATAS do arquivo (releia com read_file se preciso).")
        lines[i:i + len(old)] = new
        pos = i + len(new)
    out = "\n".join(lines)
    return out + "\n" if text.endswith("\n") or not text else out


def patch_paths(text: str) -> list[str]:
    """Todos os paths citados no patch (p/ classificação de aprovação) — tolerante a patch malformado."""
    out = []
    for raw in (text or "").splitlines():
        m = _HEADER.match(raw) or _MOVE.match(raw)
        if m:
            out.append(m.group(m.lastindex).strip())
    return out


class ApplyPatch(Tool):
    name = "apply_patch"
    description = ("Aplica um PATCH multi-arquivo num envelope só (Update/Add/Delete/Move File) com "
                   "hunks de contexto e matching tolerante a whitespace. Prefira a isto quando a "
                   "mudança toca VÁRIOS arquivos ou vários trechos; p/ UMA substituição pontual, "
                   "edit_file basta. Formato: '*** Begin Patch' / '*** Update File: x' / linhas "
                   "' ' contexto, '-' remove, '+' adiciona / '*** End Patch'.")
    args_schema = {"patch": "o envelope completo (*** Begin Patch … *** End Patch)"}
    required = ("patch",)

    def run(self, args, ctx):
        from okami.core.file_safety import MAX_WRITE_BYTES, read_text_capped, write_text_atomic
        raw = args.get("patch")
        if not isinstance(raw, str) or not raw.strip():
            return ToolResult(False, "apply_patch: 'patch' precisa ser o envelope (string não-vazia).")
        try:
            ops = parse_patch(raw)
        except PatchError as e:
            return ToolResult(False, f"patch inválido: {e}")
        yolo = getattr(ctx.sandbox, "mode", "") == "yolo"
        plan: list[tuple[PatchOp, object, object, str | None]] = []   # (op, src_path, dst_path, novo_texto)
        # FASE 1 — valida e computa TUDO (nenhuma escrita ainda): atômico entre arquivos.
        try:
            for op in ops:
                for rel in filter(None, (op.path, op.move_to)):
                    if not yolo and _SENSITIVE_PATH.search(rel):
                        return ToolResult(False, "patch toca caminho sensível (.env/.ssh/credenciais/"
                                          f"*.pem/*.key) — bloqueado. ({rel})")
                src = _safe_path(ctx, op.path)
                dst = _safe_path(ctx, op.move_to) if op.move_to else src
                if op.kind == "add":
                    if src.exists():
                        return ToolResult(False, f"Add File: '{op.path}' já existe — use Update File "
                                          "(com hunks) p/ alterar.")
                    content = "\n".join(line for h in op.hunks for tag, line in h if tag == "+")
                    plan.append((op, src, dst, content + "\n"))
                    continue
                if not src.exists():
                    return ToolResult(False, f"{op.kind.title()} File: '{op.path}' não existe — confira "
                                      "o caminho (list_dir/find_files).")
                if op.kind == "delete":
                    plan.append((op, src, dst, None))
                    continue
                if op.path not in ctx.read_files:      # grounding: igual edit_file
                    return ToolResult(False, f"'{op.path}' existe mas você não o leu — use read_file "
                                      "antes de aplicar patch (grounding).")
                # Move sobre destino EXISTENTE não-lido = sobrescrita destrutiva às cegas → recusa
                # (mesma postura do write_file; era o gap #9 do review).
                if op.move_to and dst != src and dst.exists() and op.move_to not in ctx.read_files:
                    return ToolResult(False, f"Move to: '{op.move_to}' já existe e você não o leu — "
                                      "leia-o antes (grounding) ou escolha outro destino.")
                text = read_text_capped(src, limit=MAX_WRITE_BYTES)
                plan.append((op, src, dst, apply_hunks(text, op.hunks, op.path)))
        except PatchError as e:
            return ToolResult(False, f"patch não aplicado (nada foi alterado): {e}")
        except ValueError as e:                        # path-escape do jail
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001 — leitura falhou etc.
            return ToolResult(False, f"patch não aplicado (nada foi alterado): {e}")
        # FASE 2 — executa. ATÔMICO ENTRE ARQUIVOS de verdade (#8): guarda o conteúdo ORIGINAL de cada
        # alvo antes de tocar; se QUALQUER escrita/move/delete falhar no meio, RESTAURA tudo (rollback)
        # e reporta — em vez de deixar metade dos arquivos mutada.
        backups: list[tuple[object, bytes | None]] = []   # (path, conteúdo original ou None se não existia)
        done: list[str] = []
        try:
            for op, src, dst, content in plan:
                if ctx.checkpoints is not None:
                    try:
                        ctx.checkpoints.snapshot(op.path)
                    except Exception:  # noqa: BLE001 — checkpoint é best-effort
                        pass
                if op.kind == "delete":
                    backups.append((src, src.read_bytes() if src.exists() else None))
                    self._to_trash(src)
                    done.append(f"delete {op.path}")
                    continue
                backups.append((dst, dst.read_bytes() if dst.exists() else None))
                if op.move_to and src != dst:
                    backups.append((src, src.read_bytes() if src.exists() else None))
                dst.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomic(dst, content or "")
                if op.move_to and src != dst:
                    src.unlink(missing_ok=True)
                    done.append(f"update {op.path} → {op.move_to}")
                else:
                    done.append(f"{op.kind} {op.path}")
                ctx.read_files.add(op.move_to or op.path)
        except Exception as e:  # noqa: BLE001 — falha no meio da escrita → desfaz o que já mexeu
            for path, original in reversed(backups):
                try:
                    if original is None:
                        path.unlink(missing_ok=True)        # não existia antes → remove o que criamos
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(original)          # restaura o conteúdo original
                except Exception:  # noqa: BLE001 — best-effort no rollback
                    pass
            return ToolResult(False, f"patch FALHOU no meio e foi REVERTIDO (nenhuma mudança "
                              f"permanente): {e}", effect=False)
        return ToolResult(True, "patch aplicado: " + "; ".join(done), effect=True)

    @staticmethod
    def _to_trash(p) -> None:
        """Delete REVERSÍVEL (mesma lixeira do delete_path)."""
        import shutil
        import time
        from okami.home import okami_home
        trash = okami_home() / "trash" / time.strftime("%Y%m%d-%H%M%S")
        trash.mkdir(parents=True, exist_ok=True)
        dst = trash / p.name
        if dst.exists():
            dst = trash / f"{p.name}.{len(list(trash.iterdir()))}"
        shutil.move(str(p), str(dst))
