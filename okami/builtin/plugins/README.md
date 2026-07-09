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

## Plugins nesta pasta

- **`security-guidance/`** — **port do built-in do Hermes** (funcional). Hook `before_tool` que varre o
  código a ser escrito (`write_file`/`edit_file`/`apply_patch`) por ~28 padrões inseguros e imprime um
  advisory. WARN por padrão; `OKAMI_SECURITY_GUIDANCE_BLOCK=1` → VETA a escrita.
- **`disk-cleanup/`** — **port do built-in do Hermes** (funcional). Hooks `before_tool` (rastreia efêmeros)
  + `after_task` (apaga no fim). Conservador: só `.tmp`/`.bak`/`~`/dirs `tmp|temp|scratch`, nunca symlink/dir.
- **`usage-observer/`** — exemplo de manifesto `after_tool` (ponto de extensão p/ telemetria própria; sem
  script = no-op). A observabilidade nativa (event log, `okami cost`, `okami insights`) já cobre o caso comum.
- **`git-context/`** — plugin novo (não existe assim no Hermes; usa `ctx.register_context` do sistema
  UNIFICADO, `pre_llm_call`). Injeta branch + ahead/behind do upstream + arquivos sujos do repo git do
  workspace no contexto de CADA turno — o modelo sabe onde está sem gastar uma tool call em `git status`.
  Fail-safe: fora de repo git / sem `git` no PATH → string vazia (silêncio). `OKAMI_GITCONTEXT_DISABLE=1`
  desliga; `OKAMI_GITCONTEXT_MAX_FILES` limita quantos nomes de arquivo lista antes de resumir em "+N mais".

## Paridade com os plugins built-in do Hermes

Os built-in do Hermes (`hermes-agent/docs/.../built-in-plugins`) mapeiam assim no Okami:

| Built-in do Hermes | Estado no Okami |
|---|---|
| `security-guidance` | **Portado** como plugin (`plugins/security-guidance/`, hook `before_tool`). |
| `disk-cleanup` | **Portado** como plugin (`plugins/disk-cleanup/`, `before_tool`+`after_task`). |
| `image_gen/openai`, `openai-codex`, `xai` | **Nativo**: tool `generate_image` + registry de backends nomeados (G4). |
| `kanban/dashboard` | **Nativo**: Kanban swarm do dispatcher multi-agente (#12 Onda C). |
| `observability/langfuse`, `nemo_relay` | **Nativo**: event log + `okami cost` + `okami insights` + telemetria; relé externo via hook `after_tool` (ver `usage-observer/`). |
| `google_meet`, `teams_pipeline`, `spotify` | **Superfície MCP**: integrações externas OAuth-pesadas vivem como servidores MCP soberanos (mesma decisão do computer-use), não como plugin de pasta. |
| `hermes-achievements` | Fora de escopo (gamificação de histórico de sessão); sem equivalente planejado. |

Princípio: o que já é **tool embutida** não vira plugin redundante; o que é **hook de ciclo de vida**
(security-guidance, disk-cleanup) é portado como plugin real; o que é **integração externa pesada** fica
na superfície **MCP**, não num plugin de pasta.

### Avaliado e DESCARTADO (não vira plugin — evita filler)

- **"tool-audit"/"command-logger" via `post_tool_call`** (logar comando destrutivo pra revisão depois):
  redundante com o que JÁ existe nativo — `.okami/audit.jsonl` grava TODA tool call + decisão de
  aprovação com HMAC ENCADEADO (tamper-evident, `Harness._audit` em `core/harness/loop.py`), e comando
  catastrófico já é BLOQUEADO incondicionalmente antes de rodar (`detect_hardline` em `core/approval.py`
  + Tirith em `run_shell`). Um plugin de log adicional duplicaria uma trilha que já é mais completa e
  mais forte (encadeada) do que qualquer coisa que um hook `post_tool_call` conseguiria escrever.
- **Demais built-in do Hermes em `plugins/*`** (browser, memory, model-providers, platforms, web, cron,
  dashboard_auth, observability, image/video gen) não são hooks de ciclo de vida — são INTEGRAÇÕES com
  serviço externo; já mapeadas na tabela acima como nativo/MCP. Nada ali sobra pra portar como plugin
  de hook.
