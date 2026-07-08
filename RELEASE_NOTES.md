# Okami Agent — `v0.11.0-beta` "As Três Reclamações" 🐺

**1 commit denso · 5 ondas paralelas** · suíte **3.364 → 3.443 testes** · lançada no **MESMO DIA** da
`v0.10.0-beta` (2026-07-08).

> ⚠️ **Beta.** A superfície de comandos e config ainda pode mudar até a GA. Recomendado para uso real
> (inclusive em VPS 24/7) — mas rode `okami policy check --strict` antes de expor publicamente. Feedback
> é muito bem-vindo. Ver o [CHANGELOG](CHANGELOG.md) completo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## A história desta release

A `v0.10.0-beta` saiu de manhã, promovida por maturidade depois da auditoria E2E vs Hermes. No mesmo dia,
o dono trouxe **3 reclamações diretas**, de uso real, sem rodeio:

1. **"Não consigo trocar fácil de provider ou de modelo."** Cada canal (CLI, `/model` no Telegram,
   config) resolvia alias de um jeito diferente — sem validação, sem lista, sem persistência.
2. **"Nossas chamadas de tools são péssimas."** Todo parâmetro de "modo" era texto livre pro modelo
   chutar — sem `enum`, sem `default`, sem `min`/`max`. Um bug real disso: `spawn.background` sem tipo
   declarado deixava a string `"false"` virar `True` no runtime.
3. **"Não preciso de skill para pokemon, mas seria legal skill pra workflow, pra pesquisa e etc."** As
   skills builtin eram mais demonstração do que ferramenta do dia a dia.

Cada reclamação virou uma análise curta e uma onda de correção — e no meio do caminho apareceram mais duas
frentes que dependiam da mesma limpeza: a cadeia de fuzzy-match do `edit` (pra parar de escolher sozinho
entre matches ambíguos) e o hook `transform_tool_result` nos plugins (pra security-guidance virar aviso em
vez de veto mudo). Cinco ondas, um commit, um dia.

**Validação de ponta a ponta:** rodamos o cenário real de novo com minimax — task terminou `COMPLETE` com
auto-verificação mecânica (`od`/`wc`/`sha256`), e no meio da execução o próprio agente **interceptou e
corrigiu sozinho** um bug de `echo -n` que teria corrompido o output. É o tipo de correção que só aparece
quando o schema da tool é rico o suficiente pra o modelo perceber que algo saiu errado.

## ✨ Highlights

- **`okami model`** — comando novo: picker interativo, switch direto, `list --json`. Resolver único
  (`okami/llm/model_aliases.py`) com aliases semânticos (`sonnet`, `opus`, `haiku`, `codex`, `gpt`,
  `minimax`, `mimo`, `grok`, …) e tiers dinâmicos `fast`/`smart`, validados contra o catálogo de
  providers — extensível via `model_aliases:` no yaml.
- **`/model` no Telegram usa o MESMO resolver** — ganhou `--save` (persiste em `okami.local.yaml`) e
  `/models` numerado, pra trocar de modelo do celular sem digitar nome completo.
- **Typo de alias vira erro com sugestão** (did-you-mean) em vez de aplicar silenciosamente um override
  errado.
- **Schema de tool rico** — `to_openai_schema` agora emite `enum`/`default`/`minimum`/`maximum`; antes
  todo parâmetro de modo era texto livre e o modelo chutava. Corrigido em `search_files`, `spawn_jobs`,
  `todo_write`, `spawn`, `manage_skill`, `browse`.
- **Bug real corrigido**: `spawn.background` sem tipo `boolean` fazia a string `"false"` virar `True`.
- **Edit ganha 3 estratégias fuzzy novas** (`escape_normalized`, `trimmed_boundary`, `block_anchor`) —
  paridade com a cadeia de 9 estratégias do Hermes; mais de 1 match continua sendo tratado como ambíguo,
  o edit nunca escolhe sozinho. Did-you-mean top-3 com número de linha.
- **4 skills builtin práticas**: `watchers` (RSS/GitHub/JSON com watermark dedup — base do "me avisa
  quando X mudar"), `pesquisa-web` com scripts de arxiv+wikipedia, `stocks` (Yahoo Finance sem API key),
  `github` (CI/merge/issues, `gh`-first).
- **`security-guidance` vira aviso, não veto mudo** — o hook `transform_tool_result` anexa o aviso ao
  resultado da tool; o próprio modelo vê e se autocorrige, em vez de a tool simplesmente falhar sem
  explicação.
- **`todo_write`** ganha leitura sem args, merge por `id`, status `cancelled` (paridade com o
  `TODO_SCHEMA` do Hermes).

## 🔀 Troca de modelo

- `okami/llm/model_aliases.py`: resolver único de alias/tier, validado contra o catálogo de providers.
- `okami model`: picker / switch / `list --json`.
- `/model` no gateway usa o mesmo resolver, com `--save` e `/models` numerado.
- Did-you-mean em vez de override silencioso em typo de alias.

## 🛠️ Tools

- `to_openai_schema` emite `enum`/`default`/`minimum`/`maximum` (`arg_constraints`), aplicado em 6 tools.
- `spawn.background`: bug de tipo booleano corrigido (`"false"` virava `True`).
- `todo_write`: leitura sem args, merge por `id`, status `cancelled`.

## ✏️ Edit

- Cadeia de estratégias fuzzy: `escape_normalized`, `trimmed_boundary`, `block_anchor` — paridade com o
  Hermes; ambiguidade nunca é resolvida por escolha automática.
- Did-you-mean top-3 com números de linha; `read_file` ganha `line_numbers` opt-in.

## 🧩 Skills

- `watchers`: RSS/GitHub/JSON com poll + watermark dedup, pra cron → Telegram.
- `pesquisa-web`: scripts de arxiv + wikipedia com HTTP compartilhado.
- `stocks`: Yahoo Finance sem API key.
- `github`: CI/merge/issues, `gh`-first com fallback.
- Frontmatter `requires_tools`/`fallback_for_tools` esconde skill sem tooling disponível.

## 🔌 Plugins

- Hook `transform_tool_result`: não-bloqueante, componível, isolado por plugin.
- `security-guidance`: veto vira aviso anexado ao resultado da tool.

## ✅ Release verification

- **3.443 testes** passando (`uv run pytest -q`), subindo de 3.364.
- E2E real (minimax): task `COMPLETE` com auto-verificação mecânica (`od`/`wc`/`sha256`), incluindo
  auto-correção de um bug de `echo -n` no meio da execução.
- Reprodução local:
  ```bash
  uv sync --frozen
  uv run pytest -q
  uv run ruff check okami tests
  uv run bandit -c pyproject.toml -r okami -q
  uv run okami policy check --strict
  ```

## ⚠️ Beta — o que ainda pode mudar

- Comandos e chaves de config ainda podem mudar até a GA (sem promessa de estabilidade de superfície).
- Recomendado pra uso real (VPS 24/7 inclusive), mas rode `okami policy check --strict` antes de expor
  publicamente e acompanhe o [CHANGELOG](CHANGELOG.md) a cada atualização.
- **Em andamento, fora desta release**: 3 fixes de provider (crash de streaming do Claude, token store do
  401 no Codex, parser do `claude_cli`) rodando em sessões separadas — devem sair numa próxima patch.

## 🚀 Instalação / upgrade

```bash
# instalação nova (macOS / Linux)
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
# Windows (PowerShell)
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex

# upgrade de instalação existente
uv tool upgrade okami-agent   # ou: pip install -U okami-agent

okami setup     # configura em 2-3 cliques
okami doctor    # confirma que a versão instalada bate com o pyproject (sem version-drift)
okami chat      # conversa no terminal
```

Nenhuma migração manual de config é necessária — `okami.yaml`/`okami.local.yaml` existentes continuam
válidos.

## 📄 License

**MIT** ([LICENSE](https://github.com/OkamiOps/Okami-Agent/blob/main/LICENSE)) © 2026 OkamiOps — use it,
fork it, ship it commercially, no strings attached and no warranty.

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
- 📋 Changelog completo: [CHANGELOG.md](CHANGELOG.md)
