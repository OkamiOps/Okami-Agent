"""Corpus de dicas contextuais — one-liners ensinando features REAIS do Okami.

Um lugar só p/ as "dicas do dia": a CLI/loop pega uma tip (determinística por seed, ou
aleatória) e mostra ao dono. Sem dependência nova (random é stdlib). Best-effort por design:
`get_tip` nunca levanta — no pior caso devolve a primeira tip.

Regra do corpus: cada linha cita um comportamento que existe DE VERDADE (slash-command, tool
ou subcomando da CLI). Curtas (<140 chars), sem segredo embutido, sem duplicata.
"""
from __future__ import annotations

import random

# Cada entrada ensina UMA feature real, no formato "gatilho → o que faz".
TIPS: list[str] = [
    "/model troca o modelo da sessão na hora, sem reiniciar o agente.",
    "remote_connect <host> opera noutra máquina via SSH/Tailscale, como se fosse local.",
    "@arquivo.py:10-50 injeta só essas linhas no contexto — nada de colar o arquivo inteiro.",
    "okami backup salva todo o ~/.okami (config, memória, sessions, skills) num zip.",
    "okami import restaura um backup .okami em outra máquina — migração sem dor.",
    "okami dump gera um status colável da sessão p/ você levar pra outro lugar.",
    "/copy copia a última resposta pro clipboard — funciona até por SSH (OSC-52).",
    "clarify: em ambiguidade o agente PERGUNTA antes de agir, em vez de chutar.",
    "suggest_automation propõe uma rotina e espera você aceitar antes de criar.",
    "/usage mostra tokens gastos e custo estimado da sessão.",
    "okami remote add prod <nó> registra um host remoto com apelido p/ reusar depois.",
    "okami remote list mostra os hosts remotos já cadastrados e seus apelidos.",
    "store_secret guarda uma credencial sem ecoar o valor na tela nem no log.",
    "/clear esvazia o contexto da sessão mantendo a config — recomeço limpo.",
    "@pasta/ injeta a árvore da pasta no contexto sem despejar o conteúdo todo.",
    "run_shell roda comando local; com host remoto, roda lá via SSH transparente.",
    "/usage --csv exporta o consumo de tokens da sessão p/ planilha.",
    "okami doctor checa o ambiente (auth, deps, rede) e aponta o que falta.",
    "okami remote remove <apelido> tira um host remoto da lista de hosts salvos.",
    "/model sem argumento lista os modelos disponíveis pra você escolher.",
    "web_search busca na web e cita as fontes — sem inventar link que não abriu.",
    "@arquivo.py (sem range) injeta o arquivo inteiro quando você quer tudo mesmo.",
    "redact mascara segredos em qualquer texto antes de ir pro log ou auditoria.",
    "okami backup --out <dir> escolhe onde gravar o zip do snapshot do ~/.okami.",
    "remote_disconnect volta o agente pra máquina local depois de um remote_connect.",
    "/copy n copia a n-ésima resposta anterior, não só a última.",
    "okami remote add aceita usuário@host:porta quando o SSH não está no padrão.",
    "suggest_automation nunca cria a rotina sozinho — a decisão final é sempre sua.",
]


def get_tip(seed: int | None = None) -> str:
    """Devolve uma dica do corpus.

    `seed` int → determinístico: TIPS[seed % len(TIPS)] (estável p/ "dica do dia" por data/sessão).
    `seed` None (default) → aleatório via random.choice.
    Best-effort: nunca levanta — em qualquer erro cai na primeira tip.
    """
    try:
        if seed is None:
            return random.choice(TIPS)
        return TIPS[seed % len(TIPS)]
    except Exception:                  # corpus vazio/seed exótico não derruba o caller
        return TIPS[0] if TIPS else ""
