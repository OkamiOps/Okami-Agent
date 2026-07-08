# Okami Agent — `v0.13.0-beta` "A Imagem Real" 🐺

**1 commit · suíte 3.572 → 3.576 testes** · lançada **2026-07-08**.

> ⚠️ **Beta.** A superfície de comandos e config ainda pode mudar até a GA. Recomendado para uso real
> (inclusive em VPS 24/7) — mas rode `okami policy check --strict` antes de expor publicamente. Feedback
> é muito bem-vindo. Ver o [CHANGELOG](CHANGELOG.md) completo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## A história desta release

Depois da `v0.12.0-beta` fechar 3 gaps de uso real, o dono não deixou a barra descer pra "manter
paridade". A resposta veio direta: **"paridade não basta — acha onde o Hermes está na frente e
ULTRAPASSA."**

Fizemos o mapeamento pedido: 6 dimensões (mídia, gateway, TUI/humanização, harness/tools,
memória/skills/plugins, computer/browser), comparando ponto a ponto com o Hermes. O resultado não foi
unilateral — achamos os gaps reais que o dono já suspeitava (GPT Image via assinatura quebrado, qualidade
de tool-call, skills, humanização, profundidade de browser, edição de mídia/PDF), mas também achamos
onde **já estávamos na frente** e ninguém tinha documentado: HTML→PDF sem depender de Chromium (o Hermes
depende), identidade partida em 3 arquivos (`SOUL`/`VOICE`/`PERSONA`) contra um blob genérico único do
Hermes, checkpoints de sessão, cofre de segredo cifrado.

Esta release é a **primeira onda de implementação** desse backlog — 4 frentes em paralelo (mídia,
segurança/quick-wins, hooks, browser) mais a costura entre elas.

**O headline é o pedido #1 do dono**: geração de imagem nativa (GPT Image) estava **quebrada** — o código
antigo postava pro endpoint REST pago (`api.openai.com/v1/images`), voltava `401` porque exige uma API
key paga que o dono não tem e não quer usar (ele opera 100% via assinatura). Reescrevemos pra postar pro
**endpoint da própria assinatura codex** (`chatgpt.com/backend-api/codex/responses`, tool
`image_generation`, modelo `gpt-image-2`), com headers anti-Cloudflare corretos e resolução de
`account_id` via fallback (o claim do JWT normalmente não vem preenchido). **Verificamos ao vivo**:
gerou um PNG real de 861KB através da assinatura, texto→imagem e imagem→imagem na mesma chamada.

## ✨ Highlights

- **GPT Image nativo via assinatura codex** (pedido #1 do dono) — estava quebrado (`401` no REST pago),
  agora posta pro endpoint da assinatura; texto→imagem **e** imagem→imagem na mesma chamada;
  **verificado ao vivo** (PNG real, 861KB).
- **`codex_headers.py`** (novo) — headers anti-Cloudflare (`originator`/UA `codex_cli_rs` +
  `ChatGPT-Account-Id`), com fallback de `account_id` via `~/.codex/auth.json` quando o claim do JWT não
  vem preenchido (o caso comum).
- **Bug latente corrigido de graça**: o mesmo retrofit de headers em `transports.py` conserta um `403`
  que já existia na VPS no chat codex normal — nunca tinha sido diagnosticado até agora.
- Host de imagem precisa ser `gpt-5.5` — `gpt-5.1` retorna `HTTP 400` (documentado pra não reintroduzir).
- **Skill `editar-pdf`** (nova) — `info`/`extract`/`metadata`/`patch`/`rotate`/`merge`/`split` via
  `pypdf`, dependência lazy.
- **Barramento de hooks unificado** — 15 pontos de hook (eram ~4, em dois sistemas que não se falavam):
  pre/post tool call, pre/post LLM call, pre-verify, ciclo de vida de sessão, subagent start/stop.
- **Browser em segundo plano com sessão persistente** — clicar login → dashboard → relatório sem
  re-navegar; `scroll`/`back`/`press`/`eval` (guardado contra exfiltração)/`close_session`; screenshot
  como image block nativo; dialogs JS com auto-dismiss; idle reaper pra VPS nunca vazar Chromium.
- **`ANTISLOP.md`** (novo, versionado) — 15 padrões PT-BR anti-"cara de chatbot" injetados todo turno;
  instalação nova já nasce com o default, override local continua valendo.
- **Busca com ripgrep + fallback pure-Python** — respeita `.gitignore` nos dois caminhos.
- **SSRF confirmado sem regressão** — `net_guard` já bloqueava metadata/privado/redirect, auditoria
  formalizou o que já estava certo.

## 🎨 Mídia — GPT Image nativo via assinatura

O gap #1 do dono, agora fechado fim a fim (dependendo do fix de token-store em andamento — ver abaixo):

- `imagegen.py` reescrito: endpoint `chatgpt.com/backend-api/codex/responses` + tool `image_generation`
  (`gpt-image-2`) em vez do REST pago que dava `401`.
- Texto→imagem **e** imagem→imagem na **mesma chamada** (`input_image` parts) — não precisa de duas
  requisições separadas.
- Host obrigatoriamente `gpt-5.5` (`gpt-5.1` dá `HTTP 400`).
- `codex_headers.py` novo: headers anti-Cloudflare; `account_id` resolvido via
  `oauth.codex_account_id()` → claim do JWT (raramente presente) → fallback
  `~/.codex/auth.json` → `tokens.account_id`.
- `transports.py`: mesmo retrofit de headers no chat codex normal — conserta um `403` latente na VPS que
  vinha da mesma causa-raiz.
- Fallback automático pra `flux`/`openrouter` (`IMAGE_BACKENDS`, mesmo padrão do `videogen`);
  `GenerateImage.check()` já consulta esse fallback.
- **Verificado ao vivo pelo orquestrador**: PNG real de 861KB gerado através da assinatura, fim a fim.
- Skill nova **`editar-pdf`**: `pypdf` como dependência lazy, comandos `info`/`extract`/`metadata`/
  `patch`/`rotate`/`merge`/`split`.

## 🛡️ Segurança + quick wins

- SSRF: `net_guard` auditado e confirmado já sólido (bloqueia metadata endpoint, IP privado, redirect,
  respeita `allow_private` explícito) — plugado em `web_extract`/`browse`/`references`; documentado sem
  necessidade de mudança de código.
- Busca de arquivos com backend `ripgrep`, fallback pure-Python automático quando `rg` não está
  disponível — os dois caminhos respeitam `.gitignore`.
- `ANTISLOP.md`: 15 padrões PT-BR anti-chatbot-slop (banido "Como posso ajudar?", hedging excessivo,
  entusiasmo vazio, bullet-slop e afins) injetados no `core_block` todo turno; shipado como default
  **versionado** em `okami/builtin/identity` — instalação nova já nasce com ele, override local segue
  tendo prioridade.

## 🔌 Barramento de hooks unificado

- 15 pontos de hook (eram ~4, espalhados em dois sistemas separados): `pre_tool_call`/`post_tool_call`,
  `pre_llm_call`/`post_llm_call`, `pre_verify`, ciclo de vida de sessão, `subagent_start`/`subagent_stop`.
- Bridge dos hooks shell existentes pro barramento novo — compatibilidade retroativa mantida.
- Wiring cirúrgico em `loop.py`/`runner.py`; `register_*` novo pra plugins registrarem hooks sem tocar no
  core.

## 🌐 Browser em segundo plano + edição de PDF

- Sessão persistente (`browser_session.py`, thread-bound, com idle reaper): clicar login → dashboard →
  relatório sem re-navegar a cada passo.
- Ações novas: `scroll`, `back`, `press`, `eval` (guardado contra exfiltração de cookie/localStorage),
  `close_session`.
- Screenshot exposto como image block nativo (helper compartilhado `image_block.py`).
- Diálogos JS (`alert`/`confirm`/`prompt`) com auto-dismiss.
- Idle reaper garante que uma VPS 24/7 nunca deixa processo Chromium vazando.

## 🧭 Onde já estávamos na frente

Parte do exercício de mapeamento foi honesto nos dois sentidos — nem tudo é gap. Confirmado, sem mudança
de código nesta release:

- HTML→PDF sem depender de Chromium (o Hermes depende).
- Identidade em 3 arquivos (`SOUL`/`VOICE`/`PERSONA`) vs blob genérico único do Hermes.
- Checkpoints de sessão.
- Cofre de segredo cifrado (`v0.12.0-beta`).

## ⚠️ Beta — caveats e trabalho em andamento

- Comandos e chaves de config ainda podem mudar até a GA (sem promessa de estabilidade de superfície).
- Recomendado pra uso real (VPS 24/7 inclusive), mas rode `okami policy check --strict` antes de expor
  publicamente e acompanhe o [CHANGELOG](CHANGELOG.md) a cada atualização.
- **Em andamento, fora desta release** — 3 sessões de fix de provider rodando em paralelo:
  - Crash de streaming do Claude.
  - **Bug do token-store do Codex**: um token corrompido de 9 caracteres fica na frente do token válido
    da CLI e é usado primeiro — **esse fix é necessário pra geração de imagem funcionar fim a fim** num
    usuário novo/fresh install, mesmo com o endpoint de assinatura já corrigido nesta release.
  - Parser do `claude_cli`.

## ✅ Release verification

- **3.576 testes** passando (`uv run pytest -q`), subindo de 3.572.
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

Nenhuma dependência nova obrigatória nesta release (`cryptography>=42` já foi adicionada na
`v0.12.0-beta`) — `pypdf` é lazy (só carrega se a skill `editar-pdf` for usada). `uv sync`/
`pip install -U` já resolve; `okami.yaml`/`okami.local.yaml` existentes continuam válidos.

## 📄 License

**MIT** ([LICENSE](https://github.com/OkamiOps/Okami-Agent/blob/main/LICENSE)) © 2026 OkamiOps — use it,
fork it, ship it commercially, no strings attached and no warranty.

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
- 📋 Changelog completo: [CHANGELOG.md](CHANGELOG.md)
