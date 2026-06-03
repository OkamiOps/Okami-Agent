---
name: code-wiki
description: Gerar documentação/wiki de um codebase — overview, arquitetura, módulos e diagramas Mermaid.
triggers: [wiki, documentação, docs, arquitetura, diagrama, mermaid, onboarding, codebase]
---
# Code Wiki — documente o codebase

Use para gerar referência de um repositório (onboarding, arquitetura). NÃO use para doc de um
único arquivo, endpoint isolado, ou código em mudança ativa na mesma sessão.

## Passos
1. Resolva o repo (local ou clonado) e escaneie a estrutura (`list_dir`/`run_shell` com grep).
2. Escolha **8–10 módulos** por frequência de import, tamanho e destaque no README.
3. Escreva, em ordem, em `docs/wiki/`:
   - `README.md` (overview + mapa de módulos)
   - `architecture.md` (diagrama do sistema em Mermaid flowchart)
   - um doc por módulo, com class/sequence diagrams Mermaid
   - `getting-started.md` (e API doc se fizer sentido)

## Regras
- Cap inicial de **~20 nós** por diagrama; divida sistemas maiores.
- **Verifique que cada item do diagrama existe** no código real (anti-alucinação).
- Caminhos relativos para repo local; permalinks para repo clonado.

## Conclusão
- [ ] README + architecture + por-módulo gerados em docs/wiki/.
- [ ] Diagramas batem com o código (sem inventar componentes).
