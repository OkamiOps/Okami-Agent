---
name: apple-notes
description: Gerencia Apple Notes pelo terminal via CLI `memo` — criar, buscar, editar, mover, exportar (macOS).
triggers: [apple notes, notes.app, anota isso, cria uma nota, busca nas notas, memo cli, nota no icloud]
intent_examples:
  - "cria uma nota no Apple Notes com esse resumo"
  - "procura nas minhas notas por 'orçamento 2026'"
  - "lista as notas da pasta Trabalho"
  - "exporta essa nota pra markdown"
platforms: [darwin]
metadata:
  hermes:
    tags: [notes, apple, macos, note-taking, icloud]
    category: productivity
    requires_toolsets: [terminal]
---
# Apple Notes (memo CLI)

Gerencia o Notes.app do macOS pelo terminal usando `memo` — as notas sincronizam entre todos os
dispositivos Apple via iCloud. Só funciona em macOS com o Notes.app instalado.

## Dependência

- **macOS** com Notes.app.
- Instalação: `brew tap antoniorodr/memo && brew install antoniorodr/memo/memo`.
- Na primeira execução, o macOS pede permissão de Automação pro Notes.app (Ajustes do Sistema →
  Privacidade e Segurança → Automação) — sem isso o `memo` falha silenciosamente.
- Confira que o binário existe antes de usar: `which memo`. Se não existir, avise o usuário do passo
  de instalação em vez de tentar contornar.

## Quando usar

- Usuário pede pra criar, ver, listar ou buscar Apple Notes.
- Salvar informação no Notes.app pra acesso cross-device (iPhone/iPad/Mac).
- Organizar notas em pastas.
- Exportar nota(s) pra Markdown/HTML.

## Quando NÃO usar

- Vault do Obsidian → use a skill `obsidian` (se instalada).
- Bear Notes → app separado, não coberto por essa skill.
- Anotação só-do-agente que não precisa sincronizar → use a tool de memória do próprio Okami.

## Referência rápida

### Ver notas

```bash
memo notes                    # lista todas as notas
memo notes -f "Trabalho"      # filtra por pasta
memo notes -s "orçamento"     # busca fuzzy
```

### Criar notas

```bash
memo notes -a                 # editor interativo
memo notes -a "Título rápido" # cria já com título
```

### Editar / mover / apagar

```bash
memo notes -e                 # seleção interativa pra editar
memo notes -m                 # move nota pra outra pasta (interativo)
memo notes -d                 # seleção interativa pra apagar
```

### Exportar

```bash
memo notes -ex                # exporta pra HTML/Markdown
```

## Limitações

- Não edita notas com imagem/anexo embutido.
- Vários subcomandos são interativos (seleção por lista) — rode com `pty=true` se o terminal do
  Okami precisar de um pseudo-terminal pra isso funcionar.
- macOS + Notes.app são obrigatórios; a skill não faz sentido fora de `platforms: [darwin]`.

## Regras

1. Prefira Apple Notes quando o usuário quer sincronia entre iPhone/iPad/Mac.
2. Use a tool de memória do Okami pra anotação interna do agente que não precisa sincronizar.
3. Confirme título/conteúdo antes de criar nota, pra não poluir o Notes.app do usuário com ruído.
