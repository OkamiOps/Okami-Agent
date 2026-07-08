# Okami Agent — `v0.12.0-beta` "O Fluxo Real" 🐺

**3 commits · suíte 3.468 → 3.500 testes** · lançada **2026-07-08**.

> ⚠️ **Beta.** A superfície de comandos e config ainda pode mudar até a GA. Recomendado para uso real
> (inclusive em VPS 24/7) — mas rode `okami policy check --strict` antes de expor publicamente. Feedback
> é muito bem-vindo. Ver o [CHANGELOG](CHANGELOG.md) completo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## A história desta release

Depois da `v0.11.0-beta`, o dono não deixou passar: **"você fala que estamos em paridade e eu trago
vários pontos onde estamos anos-luz atrás do Hermes."** Não veio de auditoria de código — veio de operar
o agente de verdade, no dia a dia, e sentir a distância que o diff não mostra.

Três gaps concretos, de uso real:

1. **"Não dá pra corrigir o agente NO MEIO do turno sem cancelar tudo."** O único jeito de intervir era
   `/busy` interrupt: cancela e recomeça do zero — perde o progresso do turno inteiro por um ajuste
   pequeno.
2. **"Assinatura/token-plan não pode depender de eu logar via CLI."** O dono achava que o onboarding de
   provider exigia CLI local pra assinatura — o que inviabiliza operar 100% remoto.
3. **"Não consigo mandar uma chave pelo chat quando não tenho acesso ao `.env`."** Numa VPS remota, editar
   `.env` na mão não é sempre possível — e mandar a chave crua pro modelo ver não é aceitável.

No meio de mapear o gap #1, apareceu uma coisa pior: **uma regressão crítica autoinfligida** pela própria
onda de auditoria da `v0.10.0-beta`. `run_task`/`Harness` não aceitavam o parâmetro `set_no_interrupt`
que o endpoint do gateway já injetava desde `7939d6e` — resultado, **todo turno vindo do Telegram
estourava `TypeError`**, mascarado como um simples `❌ error`. O E2E anterior só cobria o caminho CLI
(`okami task`), que não passa por esse hook — nunca pegou. Corrigida primeiro, antes de qualquer feature
nova.

**Honestidade em vez de spin**: a alegação de "paridade com Hermes" das últimas releases era real pra
auditoria de código — mas **superestimada pra uso real**. Os 3 gaps acima só apareceram operando o agente
de verdade, não lendo diff. Esta release fecha essa lacuna e assume o erro.

## ✨ Highlights

- **Regressão crítica corrigida**: `run_task`/`Harness.__init__` agora aceitam `set_no_interrupt` —
  encerra o `TypeError` que quebrava TODO turno pelo gateway do Telegram desde a `v0.10.0-beta`.
- **Efeito colateral bom**: o demote guard do `/busy` interrupt — código morto até agora, nada setava
  `no_interrupt=True` — **passa a funcionar de verdade**; `_compact()` marca a compactação como fase
  não-interrompível.
- **`/steer <texto>`** (novo) — injeta uma mensagem direta do usuário no turno em andamento **sem
  cancelar** (marcador anti prompt-injection + nota de trust no system prompt); `/busy steer` faz toda
  mensagem nova durante um turno virar steer em vez de interromper.
- **`Session.pending_steer`** nunca perde a mensagem: drena após cada resultado de tool, defere se não há
  onde anexar; `cancel`/`stop`/`retry` limpam o pendente.
- **Onboarding de provider desbloqueado** — diagnóstico revelou que minimax/mimo/grok já eram `api_key`
  direto e Codex já era OAuth device-flow nativo; o gap real era descoberta, não arquitetura. Presets
  novos: `minimax-oauth` (assinatura), `minimax-cn` (região China), `xai-oauth` (SuperGrok/Premium+),
  `custom` reetiquetado como "traga seu próprio provider".
- **Segredo via chat** — dono remoto sem acesso ao `.env` manda a API key no Telegram; detecção no
  INBOUND do gateway ANTES do modelo ver, cofre cifrado (`Fernet`, só-ciphertext, 0600), `deleteMessage`
  automático e confirmação — o modelo só vê "🔐 guardei a credencial X", **nunca o valor cru**.
- **Bug de ordering fechado**: redação da resposta agora roda ANTES de persistir (antes vazava no
  transcript/histórico).
- **+40 testes de segurança** cobrindo o cofre e a detecção de segredo inline.

## 🔥 Regressão — gateway crashava TODO turno

Regressão da própria onda P0 (`7939d6e`, `v0.10.0-beta`): o endpoint do gateway injeta
`kw['set_no_interrupt']`, mas `run_task` não tinha o parâmetro nem `**kwargs` — toda run pelo gateway
(Telegram) estourava `TypeError`, mascarado como `❌ error`. O E2E só cobria o caminho CLI (`okami task`),
que não passa esse hook — o gateway real ficou quebrado sem ninguém perceber.

- `run_task` ganha `set_no_interrupt`, encadeado no `_hkw` (mesmo padrão do `set_remote`).
- `Harness.__init__` aceita e guarda (`self._set_no_interrupt`, no-op no CLI).
- `_compact()` passa a marcar a compactação como fase não-interrompível — o demote guard do `/busy`
  interrupt, morto desde sempre, agora funciona de verdade.
- Regressão travada em `tests/test_it11_fixes.py` (contrato runner↔Harness).

## 🎯 `/steer` — corrige o turno sem cancelar

Antes só existia `/busy` interrupt: cancela o turno em andamento e recomeça do zero. Bom pra "para tudo",
péssimo pra "ajusta uma coisa pequena sem perder o progresso".

- `/steer <texto>`: injeta uma **MENSAGEM DIRETA DO USUÁRIO** no contexto do turno já rodando, com
  marcador anti prompt-injection e uma nota explícita de trust no system prompt.
- `/busy steer`: modo em que toda mensagem nova chegando durante um turno vira steer automaticamente, em
  vez de disparar o interrupt.
- `Session.pending_steer` + `steer_source` encadeados `run_task → Harness` (mesmo padrão do
  `set_no_interrupt`); drenado após cada resultado de tool; se não houver onde anexar no momento, fica
  **deferido** (nunca perdido); `cancel`/`stop`/`retry` limpam o steer pendente.

## 🔑 Onboarding de provider — assinatura/token-plan sem CLI

Diagnóstico honesto: Okami já não dependia de CLI local pra minimax/mimo/grok (já `api_key` direto) nem
pro Codex (já OAuth device-flow nativo) — o gap era **descoberta**, não arquitetura.

- Presets novos em `provider_catalog.py`: `minimax-oauth` (assinatura), `minimax-cn` (região China,
  `api.minimaxi.com`), `xai-oauth` (SuperGrok/Premium+, `client_id` real).
- `custom` reetiquetado como "traga seu próprio provider" (token-plan / API-key / endpoint
  OpenAI-compatível).
- Nenhum transport novo — só torna visível o que já existia.

## 🔐 Segredo via chat

Cenário real: dono remoto sem acesso ao `.env` manda a chave direto no Telegram. Escolhas travadas do
dono: **"salvar, apagar e confirmar"** + **"só no cofre, nunca no LLM"**.

- Detecção no **INBOUND do gateway, ANTES do modelo ver** (`okami/core/redact.py`): prefixos de chave
  conhecidos (`ghp_`/`sk-`/`xai-`/`AKIA`/…) + padrão `NOME=valor` com keyword sensível e valor ≥12 chars
  sem espaço; guard contra falso-positivo (frase natural tipo "a senha é X" e valores curtos não
  disparam).
- Cofre cifrado novo (`okami/core/secretvault.py`): **Fernet**, chave 32B em `$OKAMI_HOME/.secret_key`
  (0600, lazy), vault JSON **só-ciphertext** (0600, escrita atômica); `resolve_secret` resolve
  `vault > env > .env`; `apply_vault_to_environ` popula `os.environ` no boot (`config._load_env`) —
  providers/oauth leem do cofre sem precisar editar nada.
- Fluxo: `vault_set` → `deleteMessage` no Telegram → confirmação `🔐 guardei a credencial X` → texto
  sanitizado in-place segue pro histórico/`run_task` — **o modelo vê só a nota, nunca o valor**.
- Bug de ordering corrigido: `redact(reply)` rodava DEPOIS de persistir — vazava no transcript/histórico;
  agora roda antes.
- Nova dependência: `cryptography>=42`.

## 🔒 Nota de segurança

O valor cru da credencial **nunca entra no contexto do modelo** em nenhum ponto do fluxo — nem no goal do
`run_task`, nem no histórico, nem na resposta antes da redação. Verificação independente confirmou: valor
cru ausente do disco (só ciphertext no vault, permissão 0600), sem falso-positivo na detecção de
linguagem natural. +40 testes de segurança cobrindo cofre + detecção inline.

## ⚠️ Beta — sobre a alegação de paridade

- A "paridade com Hermes" reportada nas releases anteriores era real pra **auditoria de código**, mas
  **superestimada pra uso real** — os 3 gaps desta release (e a regressão do gateway) só apareceram
  operando o agente de verdade, não lendo diff. Esta release fecha essa lacuna especificamente.
- Comandos e chaves de config ainda podem mudar até a GA (sem promessa de estabilidade de superfície).
- Recomendado pra uso real (VPS 24/7 inclusive), mas rode `okami policy check --strict` antes de expor
  publicamente e acompanhe o [CHANGELOG](CHANGELOG.md) a cada atualização.
- **Em andamento, fora desta release**: 3 fixes de provider (crash de streaming do Claude, token store do
  401 no Codex, parser do `claude_cli`) rodando em sessões separadas — devem sair numa próxima patch.

## ✅ Release verification

- **3.500 testes** passando (`uv run pytest -q`), subindo de 3.468.
- Reprodução local:
  ```bash
  uv sync --frozen
  uv run pytest -q
  uv run ruff check okami tests
  uv run bandit -c pyproject.toml -r okami -q
  uv run okami policy check --strict
  ```

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

Nova dependência nesta release: **`cryptography>=42`** (cofre de segredos) — `uv sync`/`pip install -U`
já resolve, nenhuma migração manual de config é necessária. `okami.yaml`/`okami.local.yaml` existentes
continuam válidos.

## 📄 License

**MIT** ([LICENSE](https://github.com/OkamiOps/Okami-Agent/blob/main/LICENSE)) © 2026 OkamiOps — use it,
fork it, ship it commercially, no strings attached and no warranty.

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
- 📋 Changelog completo: [CHANGELOG.md](CHANGELOG.md)
