"""Diretório de canais por apelido (paridade Hermes): mapeia um nome amigável ("família") ao target
cru da plataforma ("-100123") p/ o envio remoto não exigir decorar IDs. Persistido em JSON com
escrita ATÔMICA (tmp + os.replace) — sobrevive entre instâncias no mesmo path. Fail-safe de ponta a
ponta: arquivo lixo/ausente vira dict vazio, e nenhum erro de I/O derruba o caller (best-effort)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from okami.core.redact import redact


class ChannelDirectory:
    """Apelido → target, persistido em `path` (JSON {alias: target}). Re-lê o disco a cada operação:
    barato pra um diretório pequeno e garante que instâncias no mesmo path enxergam uma à outra."""

    def __init__(self, path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, str]:
        """Lê o JSON do disco. Qualquer falha (ausente, lixo, permissão) → {} — nunca levanta."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        # Só aceita mapa string→string; o resto é descartado (defensivo contra arquivo adulterado).
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int))}

    def _save(self, data: dict[str, str]) -> None:
        """Grava ATÔMICO: escreve num .tmp irmão e os.replace por cima (substituição indivisível —
        nunca deixa o destino meio-escrito nem .tmp órfão se der tudo certo). Falha de I/O é engolida."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            # best-effort: limpa o .tmp se ficou pra trás, mas não propaga o erro.
            try:
                tmp.unlink(missing_ok=True)        # type: ignore[possibly-undefined]
            except Exception:
                pass

    def add_alias(self, name: str, target: str) -> None:
        """Grava `name → target` (sobrescreve se já existir). Persistência atômica imediata."""
        if not name or not target:
            return
        data = self._load()
        data[str(name)] = str(target)
        self._save(data)

    def resolve(self, name: str) -> str | None:
        """Resolve `name` → target. Casa por APELIDO; se não houver, aceita match EXATO de um target
        já cru (idempotência: passar o alvo resolvido devolve ele mesmo). None se nada bater."""
        if not name:
            return None
        data = self._load()
        if name in data:                          # apelido conhecido
            return data[name]
        if name in data.values():                 # já é um target cru cadastrado
            return name
        return None

    def all(self) -> dict[str, str]:
        """Snapshot {alias: target}. Cópia fresca do disco — mutar o retorno não afeta o estado."""
        return self._load()

    def remove_alias(self, name: str) -> bool:
        """Remove o apelido `name`. True se existia (e regravou), False se não havia nada a remover."""
        data = self._load()
        if name not in data:
            return False
        del data[name]
        self._save(data)
        return True

    def __repr__(self) -> str:                    # redige p/ não vazar IDs/targets em log de debug
        return redact(f"ChannelDirectory(path={self.path!r}, n={len(self._load())})")
