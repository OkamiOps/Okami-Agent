"""Lint-on-write DELTA (pesquisa #6 item 6) — versão 80/20 da LSP do Hermes, com stdlib.

Após uma escrita, valida o arquivo por EXTENSÃO e devolve só o erro NOVO (que o conteúdo anterior
não tinha) — "quebrei algo?". Sem linter externo nem LSP: usa `compile` (py), `json`, `tomllib`,
`yaml`. Determinístico, barato, sem dependência. NÃO bloqueia a escrita — é um aviso.
"""
from __future__ import annotations


def _check_python(text: str) -> str | None:
    try:
        compile(text, "<lint>", "exec")
        return None
    except SyntaxError as e:
        return f"SyntaxError linha {e.lineno}: {e.msg}"
    except ValueError as e:                            # ex.: null byte
        return f"erro de parse: {e}"


def _check_json(text: str) -> str | None:
    import json
    try:
        json.loads(text)
        return None
    except ValueError as e:
        return f"JSON inválido: {e}"


def _check_toml(text: str) -> str | None:
    try:
        import tomllib
    except ModuleNotFoundError:                        # py<3.11 sem tomllib → não valida
        return None
    try:
        tomllib.loads(text)
        return None
    except tomllib.TOMLDecodeError as e:
        return f"TOML inválido: {e}"


def _check_yaml(text: str) -> str | None:
    try:
        import yaml
    except ModuleNotFoundError:
        return None
    try:
        yaml.safe_load(text)
        return None
    except yaml.YAMLError as e:
        return f"YAML inválido: {str(e).splitlines()[0] if str(e) else e}"


_CHECKERS = {
    ".py": _check_python,
    ".json": _check_json,
    ".toml": _check_toml,
    ".yaml": _check_yaml, ".yml": _check_yaml,
}


def _suffix(path: str) -> str:
    from pathlib import PurePosixPath
    return PurePosixPath(str(path)).suffix.lower()


def lint_text(path: str, text: str) -> str | None:
    """Erro de validação do `text` p/ a extensão de `path`, ou None se ok / extensão não checada."""
    checker = _CHECKERS.get(_suffix(path))
    return checker(text) if checker else None


def lint_delta(path: str, before: str, after: str) -> str:
    """Erro NOVO introduzido pela escrita: '' se o after é válido, se a extensão não é checada, ou se
    o erro JÁ existia no before (editar arquivo quebrado não nagueia). Senão, advisory de 1 linha."""
    err_after = lint_text(path, after)
    if not err_after:
        return ""
    err_before = lint_text(path, before or "")
    if err_before == err_after:                        # mesmo erro de antes → não é NOVO
        return ""
    return f"⚠ lint: {path}: {err_after}"
