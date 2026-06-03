---
name: kanban-orchestrator
description: Decompor pedidos complexos em tarefas e rotear para profiles/agentes (orquestração multi-agente).
triggers: [orquestrar, kanban, decompor, multi-agente, paralelo, workstream, delegar, profiles]
---
# Kanban Orchestrator — roteie, não execute

Use quando o pedido precisa de **vários especialistas**, paralelismo, sobreviver a reinício, ou
trilha de auditoria. Para tarefa simples de um passo, NÃO use board — delegue direto.

## Regra de ouro: "route, don't execute"
- O orquestrador **não faz o trabalho**: cria tarefas para os profiles (§10 multi-agente).
- **Uma tarefa por lane independente** — separe pedidos agrupados.
- Ligue **só dependências reais** de dados (não por semelhança de palavra).
- Atribua **só a profiles que existem** (descubra antes).

## Passos
0. Descubra os profiles disponíveis (liste os agentes/workspaces) ou pergunte ao usuário.
1. Esclareça objetivos ambíguos antes de decompor.
2. Esboce o grafo de tarefas: cada workstream → um profile; marque dependências.
3. Crie as tarefas, encadeando (`parents`) só onde a ordem importa.
4. Conclua sua própria tarefa com um resumo apontando os IDs criados.
5. Reporte ao usuário em linguagem clara: o que é paralelo vs sequencial e quem ficou com o quê.

## Conclusão
- [ ] Uma tarefa por lane; dependências só reais.
- [ ] Atribuído a profiles existentes; relato claro ao usuário.
