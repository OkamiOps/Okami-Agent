"""Bundles de skills — UM nome carrega N skills (atalho p/ ativar um conjunto de uma vez).

Um bundle é um arquivo `<dir>/<nome>.yaml` com a chave `skills:` listando os nomes das skills
que ele agrupa (ex.: "review" → code-review + run-tests + git-flow). Resolver de bundle p/ lista
de skills; quem REGISTRA/INSTALA as skills é outra camada (hub/lockfile). Aqui é só o catálogo.

Fail-safe de propósito: arquivo ausente, YAML quebrado, sem a chave `skills` ou `skills` que não é
lista devolvem [] em vez de levantar — nunca derruba o caller. Itens são coagidos p/ str e os
vazios somem, então a lista é sempre `list[str]` limpa.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def list_bundles(bundles_dir) -> list[str]:
    """Nomes dos bundles disponíveis em `bundles_dir` (cada `*.yaml` vira um nome, sem extensão).

    Best-effort: diretório inexistente/ilegível → []. `.yml` é ignorado de propósito (só `.yaml`,
    espelhando o `<name>.yaml` do load_bundle). Resultado ordenado p/ saída estável.
    """
    try:
        d = Path(bundles_dir)
        return sorted(p.stem for p in d.glob("*.yaml") if p.is_file())
    except Exception:
        # Caminho inválido / erro de I/O — bundle não é caminho crítico, devolve vazio.
        return []


def load_bundle(bundles_dir, name: str) -> list[str]:
    """Lê `<bundles_dir>/<name>.yaml` e devolve a lista da chave `skills` (str, sem vazios).

    Devolve [] se o arquivo não existe, o YAML é inválido, falta a chave `skills` ou `skills` não é
    uma lista. Nunca levanta — bundle quebrado não pode derrubar quem está montando o conjunto.
    """
    try:
        path = Path(bundles_dir) / f"{name}.yaml"
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)  # safe_load: nunca instancia objetos arbitrários
    except FileNotFoundError:
        return []
    except Exception:
        # YAML inválido, erro de I/O, caminho ruim — tudo vira "bundle vazio".
        return []

    if not isinstance(data, dict):
        return []
    skills = data.get("skills")
    if not isinstance(skills, list):
        # Ausente, escalar ou qualquer coisa que não seja lista → fail-safe.
        return []
    # Coage cada item p/ str e descarta vazios (None, "", espaços).
    out: list[str] = []
    for item in skills:
        s = str(item).strip() if item is not None else ""
        if s:
            out.append(s)
    return out
