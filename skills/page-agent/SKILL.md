---
name: page-agent
description: Embutir um copiloto de IA in-page que lê o DOM e executa instruções em linguagem natural.
triggers: [page-agent, copiloto, in-page, dom, embed, widget, assistente web]
---
# Page-Agent — copiloto dentro da página

Use para embutir um assistente em uma app web (SaaS, painel admin, ferramenta B2B) que lê o DOM
como texto e executa instruções tipo "clique em login, preencha usuário". NÃO use quando o
próprio Okami precisa dirigir o browser (use a tool de browser headless).

## Caminhos
- **Demo rápida**: um `<script>` da CDN do page-agent na página.
- **Produção**: `npm install page-agent` e configure com um endpoint LLM OpenAI-compatível
  (Qwen/OpenAI/Ollama/OpenRouter): `new PageAgent({ model, baseURL })` e mostre o painel.

## Regra de segurança (CRÍTICA)
- NUNCA exponha a chave do provedor no código do cliente em produção — faça **proxy pelo backend**.
- Em produção, valide as ações sensíveis do copiloto (go/no-go) no servidor.

## Conclusão
- [ ] Copiloto carrega e lê o DOM.
- [ ] Sem chave de provedor no front; chamadas via backend.
