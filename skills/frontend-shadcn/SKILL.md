---
name: frontend-shadcn
description: Construir frontend com ShadCN UI corretamente — instalar, inicializar, usar componentes e tokens de tema.
triggers: [shadcn, frontend, ui, componente, dashboard, página, tela, interface, landing]
library: shadcn
---
# Frontend com ShadCN UI

Você DEVE usar ShadCN UI. NÃO invente CSS. O agente instala e inicializa a lib no próprio
projeto (não assuma nada pré-instalado). Use `run_shell` para os comandos.

## 1. Projeto base (se ainda não existir)
- Next.js + TS + Tailwind:
  `npx create-next-app@latest . --typescript --tailwind --eslint --app --yes`
- Se já existir projeto, garanta Tailwind configurado.

## 2. Inicializar ShadCN (se ainda não inicializado)
- `npx shadcn@latest init` (cria `components.json` e o alias `@/components/ui`).
- Confirme que `@/components/ui` resolve.

## 3. Adicionar CADA componente ANTES de usar
- `npx shadcn@latest add button card input dialog` (apenas os necessários).
- Importe de `@/components/ui/...`.

## 4. Regras (verificadas pelo gate de UI — falhar = task_complete rejeitado)
- Componha com componentes do ShadCN.
- PROIBIDO: `<style>` cru, `style={{ }}` inline, cores hex inline (`#fff`).
- Cores/tipografia/espaçamento via TOKENS do tema (`bg-background`, `text-foreground`,
  `text-muted-foreground`, etc.) e classes Tailwind.

## Checklist de conclusão (não declare task_complete sem isto)
- [ ] `components.json` existe e `@/components/ui` resolve.
- [ ] Componentes usados foram adicionados via `shadcn add`.
- [ ] Zero hex inline / `<style>` / `style={{}}`.
- [ ] `npm run build` passa.
