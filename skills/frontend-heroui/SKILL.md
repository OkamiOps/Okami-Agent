---
name: frontend-heroui
description: Construir frontend com HeroUI corretamente — instalar, configurar provider e usar componentes/tema.
triggers: [heroui, frontend, ui, componente, dashboard, página, tela, interface, landing]
library: heroui
---
# Frontend com HeroUI

Você DEVE usar HeroUI. NÃO invente CSS. O agente instala e configura no próprio projeto.
Use `run_shell` para os comandos.

## 1. Projeto base (se ainda não existir)
- React/Next + TS + Tailwind (ex.: `npx create-next-app@latest . --typescript --tailwind --app --yes`).

## 2. Instalar e configurar HeroUI
- `npm install @heroui/react framer-motion`
- Configure o plugin do HeroUI no `tailwind.config` e o `HeroUIProvider` na raiz da app
  (envolva a aplicação com `<HeroUIProvider>`).

## 3. Usar componentes da lib
- Importe de `@heroui/react` (ex.: `import { Button, Card } from "@heroui/react"`).

## 4. Regras (verificadas pelo gate de UI — falhar = task_complete rejeitado)
- Componha com componentes do HeroUI.
- PROIBIDO: `<style>` cru, `style={{ }}` inline, cores hex inline.
- Cores/tipografia/espaçamento via TOKENS/tema do HeroUI + classes Tailwind.

## Checklist de conclusão
- [ ] `@heroui/react` instalado e `HeroUIProvider` na raiz.
- [ ] Componentes importados de `@heroui/react`.
- [ ] Zero hex inline / `<style>` / `style={{}}`.
- [ ] `npm run build` passa.
