# Computer-use no Okami — EMBUTIDO (opt-in, approval-gated) + via MCP

**TL;DR:** o Okami agora **embute** uma tool `computer_use` (mouse/teclado/tela) — **DESLIGADA por padrão**,
opt-in explícito, e com 3 camadas de segurança. Quem prefere isolamento total continua podendo usar um
**servidor MCP de computer-use** trust-gated. (No #17 isto era só-MCP; o dono optou por embutir no #20.)

## A tool embutida (`computer_use`)

Ações: `screenshot` (tira foto da tela — o modelo VÊ o desktop), `click`/`right_click`/`double_click`/
`move` (x,y), `type` (texto), `key` (combo, ex.: `cmd+c`), `scroll`. Backend: **macOS nativo**
(`screencapture` + `cliclick`, zero-dep) ou **pyautogui** (cross-platform, `okami deps install
desktop.pyautogui`).

**Segurança em 3 camadas:**
1. **Opt-in explícito** — a tool só entra no registro se `computer_use.enabled: true` no `okami.yaml` E há
   backend instalado. Desligada por padrão → o agente nem sabe que existe.
2. **HARDLINE-block** — combos destrutivos (`cmd+q`/logout, lock, sleep/shutdown, `cmd+delete`/lixeira,
   `ctrl+alt+delete`) são **recusados sempre**, antes de tocar no SO, sem override por `/yolo`.
3. **go/no-go por ação** — `danger="dangerous"` no registro → cada clique/digitação passa pela aprovação
   (deny-by-default em superfície remota; o dono aprova no terminal).

```yaml
computer_use:
  enabled: true          # default false — ligue só se quiser que o agente controle seu desktop
```

---

## Alternativa: via MCP (isolamento máximo)

Se você prefere o núcleo 100% fail-closed sem a tool embutida, NÃO ligue `computer_use.enabled` e conecte
um **servidor MCP de computer-use** — que entra **trust-gated** (não-confiável por padrão, go/no-go nas
ações perigosas). A capacidade fica disponível sem o automador morar no core.

## Por que NÃO embutir

O Hermes tem `tools/computer_use/` (controle de macOS via cua-driver). É uma capacidade real e poderosa —
mas:

1. **Conflita com a identidade fail-closed do Okami.** O agente é deny-by-default, sandbox real, jaula de
   caminho sensível, anti-SSRF, redação de segredo. Um automador que move o mouse e digita na tela do dono
   é uma superfície de ataque categoricamente diferente (clicar "Autorizar", ler a tela com segredos,
   burlar prompts de SO) que não cabe no contrato de segurança atual.
2. **É outra categoria de produto.** "Sovereign AI para PMEs" = agente de codificação confiável no
   terminal/Telegram/gateway. Virar um RPA de desktop é um pivô, não um incremento.
3. **O risco é assimétrico.** O ganho (automação de GUI) é nicho; o custo (uma regressão que clica/digita
   sozinho na máquina do dono) é severo e difícil de conter dentro do sandbox.

## Como TER computer-use, se você quiser (caminho soberano)

O Okami já integra MCP com **trust store** (`untrusted` → `reviewed` → `trusted`) e inferência de
capabilities (read/write/network/shell/secret-access). Uma tool MCP perigosa de servidor **não-confiável
EXIGE go/no-go** — exatamente o que você quer p/ controle de desktop.

1. Escolha um servidor MCP de computer-use (ex.: a referência de computer-use da Anthropic, ou um servidor
   community que exponha `screenshot`/`click`/`type`).
2. Registre no `okami.yaml` sob `mcp.servers`:

   ```yaml
   mcp:
     servers:
       computer-use:
         command: "uvx"
         args: ["some-computer-use-mcp"]
         trust: untrusted            # default — força go/no-go nas ações perigosas
         # approval_policy: always   # (opcional) exige aprovação SEMPRE, mesmo em ação "read"
   ```

3. As tools do servidor aparecem no `okami mcp`. Como o servidor é `untrusted`, cada clique/digitação passa
   pela aprovação (deny-by-default). Você mantém a soberania: o Okami orquestra, mas o controle de desktop
   é uma capacidade **opt-in, isolada e auditada**, não algo embutido no núcleo.

## Resumo

| | Hermes | Okami |
|---|---|---|
| Computer-use | embutido (cua-driver) | **via MCP trust-gated** (opt-in, go/no-go, auditado) |
| Superfície de ataque no núcleo | maior | mínima (núcleo fica fail-closed) |
| Disponível p/ quem precisa? | sim | **sim** (conecta o MCP) |

A capacidade é alcançável; a decisão é **não** colocá-la dentro do agente confiável. Se um dia o produto
pivotar p/ automação de desktop de primeira classe, isto vira um épico próprio com seu próprio modelo de
ameaça — não um item de paridade.
