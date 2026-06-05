"""Context Engine central (P2 #9 self-review) — UMA camada decide o que entra no prompt, com ORÇAMENTO.

Antes, o bloco de contexto do system prompt era `core_block + memory.inject + system_extra`
concatenado cru: sem teto e sem registro. Aqui é uma montagem por SEÇÕES com PRIORIDADE e ORÇAMENTO
de chars — a identidade/core é PROTEGIDA (nunca truncada); memória/skills cabem no que sobra. É o
lugar único e AUDITÁVEL (manifest → event log) e o ponto de extensão: arquivos abertos, diretório
atual e referências entram no futuro com um `add()`, sem reespalhar a lógica.

Sob tamanhos normais (blocos já são pré-limitados pelo memfiles e pelo recall) a saída é IDÊNTICA à
concatenação antiga — então o motor é um refactor não-regressivo + rede de segurança + observabilidade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_TRUNC = "\n[… contexto truncado p/ caber no orçamento …]"


@dataclass
class Section:
    name: str
    text: str
    priority: int            # menor entra primeiro (ordem de saída E de orçamento)
    protected: bool = False  # nunca truncar (identidade/core)
    max_chars: int = 0       # teto próprio da seção (0 = sem teto)


@dataclass
class ContextEngine:
    budget_chars: int = 24000
    sections: list[Section] = field(default_factory=list)
    _seq: int = 0

    def add(self, name: str, text: str | None, *, priority: int | None = None,
            protected: bool = False, max_chars: int = 0) -> "ContextEngine":
        """Acrescenta uma seção (ignora vazia). priority default = ordem de inserção."""
        if text and text.strip():
            self._seq += 10
            self.sections.append(Section(name, text.strip(),
                                         self._seq if priority is None else priority, protected, max_chars))
        return self

    def build(self) -> tuple[str, list[dict]]:
        """Monta o bloco por prioridade dentro do orçamento. Devolve (texto, manifest p/ auditoria)."""
        out: list[str] = []
        manifest: list[dict] = []
        used = 0
        for s in sorted(self.sections, key=lambda x: x.priority):
            text = s.text[:s.max_chars] if s.max_chars else s.text
            if s.protected:
                out.append(text)
                used += len(text)
                manifest.append({"section": s.name, "chars": len(text), "dropped": False, "truncated": False})
                continue
            remaining = self.budget_chars - used
            if remaining <= 0:
                manifest.append({"section": s.name, "chars": 0, "dropped": True, "truncated": False})
                continue
            truncated = len(text) > remaining
            if truncated:
                text = text[:remaining].rstrip() + _TRUNC
            out.append(text)
            used += len(text)
            manifest.append({"section": s.name, "chars": len(text), "dropped": False, "truncated": truncated})
        return "\n\n".join(out), manifest
