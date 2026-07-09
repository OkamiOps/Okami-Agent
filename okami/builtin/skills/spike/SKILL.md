---
name: spike
description: Experimento descartável pra validar uma ideia antes de construir de verdade — decompõe em perguntas de viabilidade, pesquisa, constrói protótipo mínimo e dá um veredito.
triggers: [spike, protótipo, prototipo, experimento, prova de conceito, poc, testa se dá, viabilidade, antes de construir]
intent_examples:
  - "deixa eu ver se isso funciona antes de construir"
  - "faz um spike disso"
  - "quero comparar essas duas abordagens antes de decidir"
  - "isso é sequer possível?"
  - "protótipo rápido de Z"
metadata:
  hermes:
    tags: [spike, prototype, experiment, feasibility, throwaway, exploration, research, planning, mvp, proof-of-concept]
    related_skills: [depuracao-sistematica]
    category: software-development
    ported_from: hermes-agent/skills/software-development/spike
---

# Spike

Use esta skill quando o dono quer **sentir uma ideia** antes de se comprometer com uma construção
de verdade — validar viabilidade, comparar abordagens, ou trazer à tona incógnitas que nenhuma
quantidade de pesquisa vai responder sozinha. Spikes são descartáveis por design. Jogue fora
depois que pagaram sua dívida.

Carregue isto quando o dono disser coisas como "deixa eu tentar isso", "quero ver se X funciona",
"faz um spike disso", "antes de eu comprometer com Y", "protótipo rápido de Z", "isso é sequer
possível?", ou "compara A vs B".

## Quando NÃO usar

- A resposta é conhecida a partir de docs ou de ler o código — só pesquise, não construa.
- O trabalho é caminho de produção — use planejamento normal em vez disso.
- A ideia já está validada — vá direto pra implementação.

## Método central

Independente da escala, todo spike segue este loop:

```
decompor  →  pesquisar  →  construir  →  veredito
   ↑_________________________________________↓
                itera sobre os achados
```

### 1. Decompor

Quebre a ideia do dono em **2-5 perguntas de viabilidade independentes**. Cada pergunta é um
spike. Apresente como tabela com framing Given/When/Then:

| # | Spike | Valida (Given/When/Then) | Risco |
|---|-------|---------------------------|-------|
| 001 | streaming-websocket | Dado uma conexão WS, quando o LLM faz stream de tokens, então o cliente recebe chunks < 100ms | Alto |
| 002a | parse-pdf-pdfjs | Dado um PDF multi-página, quando parseado com pdfjs, então texto estruturado é extraível | Médio |
| 002b | parse-pdf-camelot | Dado um PDF multi-página, quando parseado com camelot, então texto estruturado é extraível | Médio |

**Tipos de spike:**
- **padrão** — uma abordagem respondendo uma pergunta
- **comparação** — mesma pergunta, abordagens diferentes (mesmo número, sufixo de letra `a`/`b`/`c`)

**Boa pergunta de spike:** viabilidade específica com saída observável.
**Má pergunta de spike:** ampla demais, sem saída observável, ou só "ler a doc sobre X".

**Ordene por risco.** O spike com maior chance de matar a ideia roda primeiro. Não faz sentido
prototipar a parte fácil se a parte difícil não funciona.

**Pule a decomposição** só se o dono já sabe exatamente o que quer spikar e disse isso. Aí trate a
ideia dele como um spike único.

### 2. Alinhar (para ideias com múltiplos spikes)

Apresente a tabela de spikes. Pergunte: "Constrói todos nessa ordem, ou ajusta?" Deixe o dono
descartar, reordenar ou reformular antes de escrever qualquer código.

### 3. Pesquisar (por spike, antes de construir)

Spike não é livre de pesquisa — você pesquisa o suficiente pra escolher a abordagem certa, depois
constrói. Por spike:

1. **Resuma.** 2-3 frases: o que é este spike, por que importa, risco-chave.
2. **Traga abordagens concorrentes** se houver escolha real:

   | Abordagem | Ferramenta/Lib | Prós | Contras | Status |
   |-----------|-----------------|------|---------|--------|
   | ... | ... | ... | ... | mantida / abandonada / beta |

3. **Escolha uma.** Diga por quê. Se 2+ são plausíveis, construa variantes rápidas dentro do
   spike.
4. **Pule a pesquisa** para lógica pura sem dependência externa.

Use busca web e leitura de documentação/código para essa etapa — pesquise bibliotecas/ferramentas
candidatas, leia a doc real (não confie só no nome), e confira o que já está instalado no
ambiente do projeto (`pip show`, `npm ls`, etc.).

### 4. Construir

Um diretório por spike. Mantenha standalone.

```
spikes/
├── 001-streaming-websocket/
│   ├── README.md
│   └── main.py
├── 002a-parse-pdf-pdfjs/
│   ├── README.md
│   └── parse.js
└── 002b-parse-pdf-camelot/
    ├── README.md
    └── parse.py
```

**Prefira algo com que o dono possa interagir.** Spikes fracassam quando a única saída é uma
linha de log dizendo "funcionou". O dono quer *sentir* o spike funcionando. Escolhas padrão, em
ordem de preferência:

1. Um CLI executável que recebe input e imprime saída observável
2. Uma página HTML mínima que demonstra o comportamento
3. Um pequeno servidor web com um endpoint
4. Um teste unitário que exercita a pergunta com asserções reconhecíveis

**Profundidade acima de velocidade.** Nunca declare "funciona" depois de um único caminho feliz.
Teste casos de borda. Siga achados surpreendentes. O veredito só é confiável quando a investigação
foi honesta.

**Evite** a menos que o spike exija especificamente: gerenciamento complexo de pacote,
bundler/build tool, Docker, arquivos de env, sistema de config. Fixe tudo (hardcode) — é um spike.

**Construindo um spike** — sequência típica:

```bash
mkdir -p spikes/001-streaming-websocket
# escreve spikes/001-streaming-websocket/README.md com a pergunta e o plano
# escreve spikes/001-streaming-websocket/main.py com o protótipo
cd spikes/001-streaming-websocket && python3 main.py
# observa a saída, itera.
```

**Spikes de comparação em paralelo (002a / 002b) — delegue.** Quando duas abordagens podem rodar
em paralelo e ambas exigem engenharia de verdade (não protótipo de 10 linhas), lance duas
sub-tarefas concorrentes (uma para cada abordagem, cada uma com o objetivo e o toolset
apropriado) e deixe cada uma retornar seu próprio veredito — você escreve o comparativo final.

### 5. Veredito

O `README.md` de cada spike fecha com:

```markdown
## Veredito: VALIDADO | PARCIAL | INVALIDADO

### O que funcionou
- ...

### O que não funcionou
- ...

### Surpresas
- ...

### Recomendação pra construção real
- ...
```

**VALIDADO** = a pergunta central foi respondida sim, com evidência.
**PARCIAL** = funciona sob as restrições X, Y, Z — documente-as.
**INVALIDADO** = não funciona, por este motivo. Isso é um spike bem-sucedido.

## Spikes de comparação

Quando duas abordagens respondem a mesma pergunta (002a / 002b), construa-as **uma atrás da
outra**, depois faça um comparativo cabeça-a-cabeça no final:

```markdown
## Cabeça-a-cabeça: pdfjs vs camelot

| Dimensão | pdfjs (002a) | camelot (002b) |
|----------|--------------|-----------------|
| Qualidade de extração | 9/10 estruturado | 7/10 só tabela |
| Complexidade de setup | npm install, 1 linha | pip + ghostscript |
| Perf em PDF de 100 páginas | 3s | 18s |
| Lida com texto rotacionado | não | sim |

**Vencedor:** pdfjs para o nosso caso de uso. Camelot se precisarmos de extração table-first no
futuro.
```

## Modo fronteira (escolhendo o próximo spike)

Se já existem spikes e o dono pergunta "o que eu deveria spikar agora?", percorra os diretórios
existentes e procure por:

- **Riscos de integração** — dois spikes validados que tocam o mesmo recurso mas foram testados
  independentemente
- **Handoffs de dado** — a saída do spike A foi assumida compatível com a entrada do spike B;
  nunca provado
- **Lacunas na visão** — capacidades assumidas mas não comprovadas
- **Abordagens alternativas** — ângulos diferentes para spikes PARCIAL ou INVALIDADO

Proponha 2-4 candidatos como Given/When/Then. Deixe o dono escolher.

## Saída

- Crie `spikes/` na raiz do repo
- Um diretório por spike: `NNN-nome-descritivo/`
- `README.md` por spike captura pergunta, abordagem, resultados, veredito
- Mantenha o código descartável — um spike que leva 2 dias pra "limpar pra produção" foi um mau
  spike

## Atribuição

Método adaptado do workflow `/gsd-spike` do projeto GSD (Get Shit Done) — MIT © 2025 Lex
Christopherson ([gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)), via o
porte feito pelo Hermes Agent.
