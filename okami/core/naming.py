"""Nomes/ids CURTOS e legíveis a partir de texto livre — usado por skills auto-criadas e cron jobs.

A dor: o agente nomeava skill/job com a FRASE LITERAL do usuário ("agora vou pedir pra voce analisar
seu codigo") slugificada e truncada. Aqui geramos um nome de TÓPICO: tira acento, remove fillers
conversacionais, descarta verbo genérico quando precisa encurtar, e fica com 2-3 palavras de conteúdo.
"""

from __future__ import annotations

import re
import unicodedata

# Fillers conversacionais (PT-BR + EN) que NUNCA entram num nome.
_STOP = frozenset({
    # PT-BR
    "a", "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "e", "ou", "que",
    "se", "em", "no", "na", "nos", "nas", "ao", "aos", "por", "pra", "para", "com", "sem", "eu", "voce",
    "vc", "me", "te", "lhe", "agora", "aqui", "ali", "ai", "ja", "vou", "vai", "vamos", "quero", "queria",
    "quer", "pode", "poderia", "consegue", "conseguir", "faz", "fazer", "feito", "ver", "veja", "ve",
    "entao", "mais", "muito", "isso", "esse", "essa", "este", "esta", "isto", "ser", "estar", "pedir",
    "peco", "favor", "legal", "bom", "boa", "oi", "ola", "obrigado", "seu", "sua", "meu", "minha",
    "nosso", "nossa", "tudo", "coisa", "sobre", "depois", "antes", "tipo", "assim", "la", "ne", "so",
    "tem", "ter", "deu", "vamo", "preciso", "gostaria", "outros", "outro", "outra", "melhorou", "toda",
    "todo", "todas", "todos", "cada", "ainda", "tambem", "tb", "mesmo", "qualquer", "algum", "alguma",
    # EN
    "the", "an", "of", "and", "or", "to", "in", "on", "for", "with", "please", "can", "could", "you",
    "i", "now", "here", "this", "that", "is", "be", "do", "make", "let", "want", "would", "my", "your",
    "we", "us", "it", "some", "thing", "stuff", "about", "every", "all",
})

# Verbos GENÉRICOS de conteúdo: ficam SÓ se sobrar espaço (descartados primeiro quando encurta).
# Mantêm o nome focado no SUBSTANTIVO/tópico (deploy-docker > criar-deploy-docker).
_GENERIC_VERBS = frozenset({
    "criar", "cria", "crie", "gerar", "gera", "gere", "configurar", "configura", "configure",
    "rodar", "roda", "rode", "analisar", "analisa", "analise", "buscar", "busca", "montar", "monta",
    "escrever", "escreve", "implementar", "implementa", "adicionar", "adiciona", "atualizar", "atualiza",
    "corrigir", "corrige", "ajustar", "ajusta", "testar", "testa", "verificar", "verifica", "revisar",
    "revisa", "melhorar", "melhora", "instalar", "instala", "mostrar", "mostra", "listar", "lista",
    "create", "make", "generate", "configure", "run", "analyze", "build", "update", "fix", "add",
    "check", "review", "install", "setup",
})


def short_name(text: str, *, tools: list[str] | None = None, max_words: int = 3,
               max_len: int = 24, fallback: str = "item") -> str:
    """Nome CURTO em kebab-case (≤max_words palavras, ≤max_len chars): tira acento, remove filler,
    e — quando passa do orçamento — descarta verbo genérico p/ manter o substantivo/tópico.
    `tools`: fallback pela tool dominante quando só sobra filler (ex.: 'run-shell-task')."""
    norm = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", norm.lower())
    words = [t for t in tokens if len(t) >= 2 and t not in _STOP]   # 'ci'/'ui'/'db' preservados; filler 2-char já no stop
    if not words:
        words = [t for t in tokens if t not in _STOP]
    if len(words) > max_words:                         # estourou → tira verbo genérico (mantém os substantivos)
        content = [w for w in words if w not in _GENERIC_VERBS]
        words = content or words
    if not words and tools:                            # só sobrou filler → nomeia pela tool dominante
        top = max(set(tools), key=tools.count)
        words = [re.sub(r"[^a-z0-9]+", "-", top.lower()), "task"]
    name = "-".join(words[:max_words])[:max_len].strip("-")
    return name or fallback
