# Plugins do Okami

O Okami descobre plugins de **duas fontes** (combináveis): esta pasta (`<projeto>/plugins/<nome>/` ou
`~/.okami/plugins/<nome>/`) e **entry-points pip** (grupo `okami.plugins`). Cada plugin declara `hooks`
no `plugin.yaml`; o `HookManager` roda os scripts em `<plugin>/hooks/<evento>/*` no ciclo de vida (antes/
depois de tool, antes de instalar skill, etc.).

> **Por que poucos plugins empacotados?** As capacidades "populares" (browser, geração de imagem, kanban/
> swarm, dashboard com auth, scan de segurança Tirith) já são **tools embutidas** no Okami — não precisam
> de plugin. Os exemplos abaixo demonstram o **sistema de extensão de terceiros**: adicionar comportamento
> via hook, sem tocar no core.

## Como criar um plugin

```
plugins/
  meu-plugin/
    plugin.yaml          # name + hooks (manifesto)
    hooks/
      before_tool/
        guard.sh         # executável; exit ≠ 0 em before_* VETA a ação
      after_tool/
        log.sh           # after_* só observa (exit ignorado)
```

`plugin.yaml`:
```yaml
name: meu-plugin
hooks: [before_tool, after_tool]
description: o que ele faz
```

Eventos: `before_tool` (pode vetar), `after_tool` (observa), `before_skill_install`, `pre_llm_call`, …
Confiança: plugin de pasta entra **untrusted** (não pode trocar de provider à revelia do dono — ver
`PluginContext` em `okami/plugins.py`). Liste com `okami plugins`.

## Exemplos nesta pasta

- **`security-guidance/`** — manifesto que declara um hook `before_tool` (ponto de extensão p/ uma política
  de segurança própria; sem script = no-op até você adicionar `hooks/before_tool/guard.sh`).
- **`usage-observer/`** — manifesto que declara um hook `after_tool` (ponto de extensão p/ telemetria
  própria; observa, nunca veta).
