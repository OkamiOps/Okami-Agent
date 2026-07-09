---
name: vercel-react-best-practices
description: Guia de performance para React/Next.js mantido pela Vercel Engineering — 70 regras em 8 categorias (waterfalls, bundle, server, client fetching, re-render, rendering, JS, avançado). Use ao escrever, revisar ou refatorar código React/Next.js para garantir padrões de performance.
triggers: [react, next.js, nextjs, performance react, otimizar bundle, re-render, server components, rsc, waterfall, refatorar react, revisa componente react]
intent_examples:
  - "revisa esse componente React pra performance"
  - "por que essa página Next.js tá lenta"
  - "otimiza esse data fetching"
  - "esse bundle tá gigante, o que cortar"
  - "refatora esse hook pra evitar re-render"
metadata:
  source: https://github.com/vercel-labs/agent-skills (skills/react-best-practices)
  license: MIT
  hermes:
    tags: [react, nextjs, performance, frontend, code-review]
    related_skills: [frontend-design, shadcn]
    category: dev
---

# Vercel React Best Practices

Skill portada do agent-skills da Vercel (`vercel-labs/agent-skills`, `skills/react-best-practices`).
Guia abrangente de otimização de performance para aplicações React e Next.js, mantido pela Vercel
Engineering. Contém 70 regras em 8 categorias, priorizadas por impacto, para orientar refatoração
automatizada e geração de código.

## Quando aplicar

Consulte estas guidelines quando:
- Escrever novos componentes React ou páginas Next.js
- Implementar data fetching (client ou server-side)
- Revisar código em busca de problemas de performance
- Refatorar código React/Next.js existente
- Otimizar tamanho de bundle ou tempo de carregamento

## Categorias de regra por prioridade

| Prioridade | Categoria | Impacto | Prefixo |
|----------|----------|--------|--------|
| 1 | Eliminating Waterfalls | CRÍTICO | `async-` |
| 2 | Bundle Size Optimization | CRÍTICO | `bundle-` |
| 3 | Server-Side Performance | ALTO | `server-` |
| 4 | Client-Side Data Fetching | MÉDIO-ALTO | `client-` |
| 5 | Re-render Optimization | MÉDIO | `rerender-` |
| 6 | Rendering Performance | MÉDIO | `rendering-` |
| 7 | JavaScript Performance | BAIXO-MÉDIO | `js-` |
| 8 | Advanced Patterns | BAIXO | `advanced-` |

## Referência rápida (nomes das 70 regras)

### 1. Eliminating Waterfalls (CRITICAL)
- `async-cheap-condition-before-await` - Check cheap sync conditions before awaiting flags or remote values
- `async-defer-await` - Move await into branches where actually used
- `async-parallel` - Use Promise.all() for independent operations
- `async-dependencies` - Use better-all for partial dependencies
- `async-api-routes` - Start promises early, await late in API routes
- `async-suspense-boundaries` - Use Suspense to stream content

### 2. Bundle Size Optimization (CRITICAL)
- `bundle-barrel-imports` - Import directly, avoid barrel files
- `bundle-analyzable-paths` - Prefer statically analyzable import and file-system paths to avoid broad bundles and traces
- `bundle-dynamic-imports` - Use next/dynamic for heavy components
- `bundle-defer-third-party` - Load analytics/logging after hydration
- `bundle-conditional` - Load modules only when feature is activated
- `bundle-preload` - Preload on hover/focus for perceived speed

### 3. Server-Side Performance (HIGH)
- `server-auth-actions` - Authenticate server actions like API routes
- `server-cache-react` - Use React.cache() for per-request deduplication
- `server-cache-lru` - Use LRU cache for cross-request caching
- `server-dedup-props` - Avoid duplicate serialization in RSC props
- `server-hoist-static-io` - Hoist static I/O (fonts, logos) to module level
- `server-no-shared-module-state` - Avoid module-level mutable request state in RSC/SSR
- `server-serialization` - Minimize data passed to client components
- `server-parallel-fetching` - Restructure components to parallelize fetches
- `server-parallel-nested-fetching` - Chain nested fetches per item in Promise.all
- `server-after-nonblocking` - Use after() for non-blocking operations

### 4. Client-Side Data Fetching (MEDIUM-HIGH)
- `client-swr-dedup` - Use SWR for automatic request deduplication
- `client-event-listeners` - Deduplicate global event listeners
- `client-passive-event-listeners` - Use passive listeners for scroll
- `client-localstorage-schema` - Version and minimize localStorage data

### 5. Re-render Optimization (MEDIUM)
- `rerender-defer-reads` - Don't subscribe to state only used in callbacks
- `rerender-memo` - Extract expensive work into memoized components
- `rerender-memo-with-default-value` - Hoist default non-primitive props
- `rerender-dependencies` - Use primitive dependencies in effects
- `rerender-derived-state` - Subscribe to derived booleans, not raw values
- `rerender-derived-state-no-effect` - Derive state during render, not effects
- `rerender-functional-setstate` - Use functional setState for stable callbacks
- `rerender-lazy-state-init` - Pass function to useState for expensive values
- `rerender-simple-expression-in-memo` - Avoid memo for simple primitives
- `rerender-split-combined-hooks` - Split hooks with independent dependencies
- `rerender-move-effect-to-event` - Put interaction logic in event handlers
- `rerender-transitions` - Use startTransition for non-urgent updates
- `rerender-use-deferred-value` - Defer expensive renders to keep input responsive
- `rerender-use-ref-transient-values` - Use refs for transient frequent values
- `rerender-no-inline-components` - Don't define components inside components

### 6. Rendering Performance (MEDIUM)
- `rendering-animate-svg-wrapper` - Animate div wrapper, not SVG element
- `rendering-content-visibility` - Use content-visibility for long lists
- `rendering-hoist-jsx` - Extract static JSX outside components
- `rendering-svg-precision` - Reduce SVG coordinate precision
- `rendering-hydration-no-flicker` - Use inline script for client-only data
- `rendering-hydration-suppress-warning` - Suppress expected mismatches
- `rendering-activity` - Use Activity component for show/hide
- `rendering-conditional-render` - Use ternary, not && for conditionals
- `rendering-usetransition-loading` - Prefer useTransition for loading state
- `rendering-resource-hints` - Use React DOM resource hints for preloading
- `rendering-script-defer-async` - Use defer or async on script tags

### 7. JavaScript Performance (LOW-MEDIUM)
- `js-batch-dom-css` - Group CSS changes via classes or cssText
- `js-index-maps` - Build Map for repeated lookups
- `js-cache-property-access` - Cache object properties in loops
- `js-cache-function-results` - Cache function results in module-level Map
- `js-cache-storage` - Cache localStorage/sessionStorage reads
- `js-combine-iterations` - Combine multiple filter/map into one loop
- `js-length-check-first` - Check array length before expensive comparison
- `js-early-exit` - Return early from functions
- `js-hoist-regexp` - Hoist RegExp creation outside loops
- `js-min-max-loop` - Use loop for min/max instead of sort
- `js-set-map-lookups` - Use Set/Map for O(1) lookups
- `js-tosorted-immutable` - Use toSorted() for immutability
- `js-flatmap-filter` - Use flatMap to map and filter in one pass
- `js-request-idle-callback` - Defer non-critical work to browser idle time

### 8. Advanced Patterns (LOW)
- `advanced-effect-event-deps` - Don't put `useEffectEvent` results in effect deps
- `advanced-event-handler-refs` - Store event handlers in refs
- `advanced-init-once` - Initialize app once per app load
- `advanced-use-latest` - useLatest for stable callback refs

## Documento completo

Cada regra acima tem explicação detalhada + exemplo incorreto vs. correto + métricas de impacto no
documento compilado, portado na íntegra: `${OKAMI_SKILL_DIR}/references/AGENTS.md`. Leia a seção da
regra relevante antes de aplicar uma refatoração de performance não-trivial.
