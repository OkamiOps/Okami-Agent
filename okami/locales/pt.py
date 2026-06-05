"""Catálogo Português (pt-BR). Tradução do default (en). Ative com OKAMI_LANG=pt ou `lang: pt` no okami.yaml."""

MESSAGES: dict[str, str] = {
    # chat / gateway help
    "chat.help": "Sou o agente '{agent}'. Manda a tarefa.\nEssenciais: {ess}\n/commands lista TODOS por categoria.",
    "chat.commands_header": "📜 comandos por categoria:",
    # TUI help table
    "tui.help.title": "Comandos",
    "tui.help.col.category": "categoria",
    "tui.help.col.command": "comando",
    "tui.help.col.does": "o que faz",
    # rótulos de categoria dos slash commands
    "cmd.cat.session": "sessão",
    "cmd.cat.model": "modelo",
    "cmd.cat.identity": "identidade",
    "cmd.cat.info": "info",
    "cmd.cat.system": "sistema",
    # descrições dos slash commands (sessão)
    "cmd.new": "começa uma conversa nova (arquiva a atual)",
    "cmd.stop": "cancela a tarefa em andamento",
    "cmd.retry": "retoma a última tarefa interrompida",
    "cmd.compact": "compacta o contexto agora (resume o que já passou)",
    "cmd.sessions": "lista as conversas arquivadas (por /new)",
    "cmd.resume": "retoma uma conversa arquivada (/resume <n>)",
    "cmd.export": "exporta a conversa atual em Markdown (/export [arquivo])",
    "cmd.topic": "conversas paralelas no mesmo chat (tópicos do Telegram = sessões separadas)",
    "cmd.background": "roda uma tarefa em paralelo e avisa quando terminar",
    "cmd.process": "supervisão de processos OS (servidor/build): status·log·kill imediato",
    "cmd.title": "dá um nome à conversa atual (/title <nome>)",
    "cmd.exit": "sai do chat",
    # modelo / raciocínio
    "cmd.model": "mostra ou troca o modelo desta sessão",
    "cmd.models": "lista os modelos disponíveis",
    "cmd.think": "esforço de raciocínio (minimal·low·medium·high·off)",
    # identidade / gosto
    "cmd.feedback": "molda o jeito do agente falar (evolui VOICE/PERSONA)",
    "cmd.persona": "muda o tom só nesta sessão (/persona off volta)",
    "cmd.undo": "reverte a última evolução de identidade",
    "cmd.like": "curtiu o design (taste)",
    "cmd.dislike": "não curtiu o design (taste)",
    "cmd.different": "quer um design diferente (taste)",
    # info
    "cmd.help": "mostra os comandos essenciais",
    "cmd.commands": "lista TODOS os comandos por categoria",
    "cmd.status": "estado da sessão (trocas, modelo, yolo)",
    "cmd.usage": "tokens + custo acumulados da sessão",
    "cmd.tools": "lista as ferramentas que o agente tem",
    "cmd.details": "verbosidade dos tool-calls: hidden | collapsed | expanded",
    "cmd.agents": "painel de atividade: turno, /background e fila",
    "cmd.skin": "troca o tema da TUI (okami | nord | dracula | …)",
    "cmd.mouse": "liga/desliga o mouse da TUI (off = seleção nativa do terminal)",
    "cmd.whoami": "mostra seu chat id (p/ allowlist)",
    # sistema
    "cmd.yolo": "auto-aprova ações sensíveis nesta sessão",
    "cmd.normal": "volta a aprovação normal",
    "cmd.voice": "liga/desliga a resposta em áudio (TTS) nesta sessão",
    "cmd.busy": "o que fazer se você escrever ocupado: queue (fila) | interrupt (corta)",
    "cmd.sethome": "define este chat como destino dos lembretes/agendamentos (cron)",
    "cmd.config": "mostra a config efetiva (segredos mascarados)",
    "cmd.reload": "recarrega a config em quente (sem reiniciar)",
}
