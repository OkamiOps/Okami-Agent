---
name: python-debug
description: Depurar Python com pdb (REPL local) e debugpy/remote-pdb (anexar em processo remoto/de longa duração via DAP ou socket) — quando print/logging não bastam.
triggers: [debug python, depurar python, pdb, debugpy, breakpoint, quebrar na linha, anexar debugger, post-mortem, step debugging]
intent_examples:
  - "isso tá com um valor errado, quero parar no meio e olhar"
  - "coloca um breakpoint aqui e roda"
  - "esse processo já tá rodando, dá pra anexar um debugger nele?"
  - "quero investigar essa exceção com post-mortem"
  - "o teste falha e o traceback não explica, quero entrar com pdb"
metadata:
  hermes:
    tags: [debugging, python, pdb, debugpy, breakpoints, dap, post-mortem]
    related_skills: [depuracao-sistematica]
    category: software-development
    ported_from: hermes-agent/skills/software-development/python-debugpy
---

# Depurador Python (pdb + debugpy)

## Visão geral

Três ferramentas, escolhidas pela situação:

| Ferramenta | Quando |
|---|---|
| **`breakpoint()` + pdb** | Local, interativo, mais simples. Adiciona `breakpoint()` no código-fonte, roda normal, ganha um REPL naquela linha. |
| **`python -m pdb`** | Lança um script existente sob pdb sem editar o fonte. Útil pra cutucar rápido. |
| **`debugpy`** | Remoto / headless / "anexar num processo já rodando". Fala DAP, scriptável do terminal, funciona pra processo de longa duração (daemon, worker, gateway). |

**Comece com `breakpoint()`.** É a coisa mais barata que já funciona.

Para achar a causa-raiz de um bug de forma metódica (não só o mecanismo de step debugging), veja
a skill `depuracao-sistematica` — esta skill aqui é o ferramental, aquela é o método.

## Quando usar

- Um teste falha e o traceback não revela por que um valor está errado
- Você precisa dar step numa função e observar uma coleção mutando
- Um processo de longa duração (daemon, worker, gateway) se comporta mal e você não pode
  reiniciá-lo
- Post-mortem: uma exceção disparou em código produção-like e você quer inspecionar os locals no
  ponto de crash
- Um subprocess/filho é o real local do bug

**Não use para:** coisa que `print()` / `logging.debug` resolve em menos de um minuto, ou coisa
que `pytest -vv --tb=long --showlocals` já revela.

## Referência rápida do pdb

Dentro de qualquer prompt pdb (`(Pdb)`):

| Comando | Ação |
|---|---|
| `h` / `h cmd` | ajuda |
| `n` | próxima linha (step over) |
| `s` | step into |
| `r` | retorna da função atual |
| `c` | continua |
| `unt N` | continua até a linha N |
| `j N` | pula pra linha N (só na mesma função) |
| `l` / `ll` | lista código ao redor da linha atual / função inteira |
| `w` | where (stack trace) |
| `u` / `d` | sobe / desce na pilha |
| `a` | imprime args da função atual |
| `p expr` / `pp expr` | imprime / pretty-print de expressão |
| `display expr` | auto-imprime expr a cada parada |
| `b file:line` | seta breakpoint |
| `b func` | quebra na entrada da função |
| `b file:line, cond` | breakpoint condicional |
| `cl N` | limpa breakpoint N |
| `tbreak file:line` | breakpoint de uma vez só |
| `!stmt` | executa Python arbitrário (inclusive atribuição) |
| `interact` | entra num REPL Python completo no escopo atual (Ctrl+D pra sair) |
| `q` | sai |

O comando `interact` é o mais poderoso — dá pra importar qualquer coisa, inspecionar objeto
complexo, até chamar método que muda estado. Locals são somente-leitura por padrão; use
`!x = 42` no prompt `(Pdb)` pra mutar.

## Receita 1: breakpoint local

Mais fácil. Edite o arquivo:

```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()           # <-- entra no pdb aqui
    return result + y
```

Rode o código normalmente. Você para na linha do `breakpoint()` com acesso total aos locals.

**Não esqueça de remover o `breakpoint()` antes de commitar.** Use `git diff` ou um grep de
pré-commit:
```bash
rg -n 'breakpoint\(\)' --type py
```

## Receita 2: lançar um script sob pdb (sem editar o fonte)

```bash
python -m pdb caminho/do/script.py arg1 arg2
# Para na primeira linha do script
(Pdb) b caminho/do/script.py:42
(Pdb) c
```

## Receita 3: depurar um teste do pytest

```bash
# Entra no pdb quando falha (ou em qualquer exceção levantada):
uv run pytest tests/caminho/test_arquivo.py::test_nome --pdb

# Entra no pdb no INÍCIO do teste:
uv run pytest tests/caminho/test_arquivo.py::test_nome --trace

# Mostra locals no traceback sem pdb:
uv run pytest tests/caminho/test_arquivo.py --showlocals --tb=long
```

Se o runner do projeto usa xdist (`-n auto` / `-n 4`), pdb NÃO funciona sob xdist — rode com
`-p no:xdist` ou `-n 0` pra testar um caso isolado.

## Receita 4: post-mortem em qualquer exceção

```python
import pdb, sys
try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

Ou envolva o script inteiro:

```bash
python -m pdb -c continue script.py
# Quando crashar, pdb captura e você entra no frame da exceção
```

Ou defina um hook global num repl/notebook:

```python
import sys
def excepthook(etype, value, tb):
    import pdb; pdb.post_mortem(tb)
sys.excepthook = excepthook
```

## Receita 5: debug remoto com debugpy (anexar em processo rodando)

Para processo de longa duração: daemon, worker persistente, um processo que já está com
problema e não pode ser reiniciado limpo.

### Setup

```bash
source .venv/bin/activate
pip install debugpy
```

### Padrão A: edita o fonte — o processo espera o debugger no lançamento

Adicione perto do topo do entry point (ou dentro da função que quer depurar):

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
print("debugpy escutando em 5678, esperando cliente...", flush=True)
debugpy.wait_for_client()
debugpy.breakpoint()       # opcional: pausa imediatamente depois de anexar
```

Inicie o processo; ele bloqueia em `wait_for_client()`.

### Padrão B: sem editar o fonte — lança com `-m debugpy`

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client seu_script.py arg1
```

Equivalente pra entry point de módulo:

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m seu.modulo
```

### Padrão C: anexar num processo já rodando

Precisa do PID e do debugpy pré-instalado no ambiente do alvo:

```bash
python -m debugpy --listen 127.0.0.1:5678 --pid <pid>
# debugpy se injeta no processo. Depois anexa um cliente como abaixo.
```

Alguns kernels/config de segurança bloqueiam a injeção via ptrace
(`/proc/sys/kernel/yama/ptrace_scope`). Corrige com:
```bash
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
```

### Anexar um cliente do terminal

O jeito mais agente-friendly de anexar do terminal sem IDE é `remote-pdb` — mais simples que
falar DAP na mão. Instale, adicione `set_trace()` no código, e conecte com `nc`. Se o dono tem
VS Code / Cursor / Zed aberto, ele também pode anexar via `launch.json` apontando pro host/porta
do `debugpy.listen`.

### Opção — descartar DAP, usar `remote-pdb`

Geralmente é o que se quer de verdade num agente de terminal:

```bash
pip install remote-pdb
```

No código:
```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)   # bloqueia até conectar
```

Depois do terminal:
```bash
nc 127.0.0.1 4444
# Ganha um prompt (Pdb) exatamente como depuração local
```

`remote-pdb` é a escolha mais limpa quando o protocolo DAP do `debugpy` é exagero. Use `debugpy`
só quando você realmente precisa de integração com IDE.

## Depurando processos de longa duração do Okami

### Testes
Ver Receita 3. Sempre adicione `-p no:xdist` ou rode teste único sem xdist.

### CLI — one-shot
Mais fácil: adicione `breakpoint()` perto da linha suspeita, depois rode o comando normalmente. O
controle volta pro seu terminal no ponto de pausa.

### Gateway / worker persistente
Se o processo roda como filho de outro processo (ex.: gateway spawnado por um supervisor), duas
opções:

**A. Edita o fonte do processo:**
```python
# perto do topo da função de entrada do gateway/worker
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
```
Inicie o processo pai normalmente. Ele vai parecer travado (o filho está esperando). Anexe um
cliente; a execução retoma quando você der `continue`.

**B. Usa `remote-pdb` num handler específico:**
```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)   # no handler que você quer capturar
```
Dispare o comando/evento correspondente, depois `nc 127.0.0.1 4444` em outro terminal.

## Armadilhas comuns

1. **pdb sob pytest-xdist não faz nada silenciosamente.** Você não vê o prompt, o teste só
   trava. Sempre use `-p no:xdist` ou `-n 0`.

2. **`breakpoint()` em CI / contexto sem TTY trava o processo.** Seguro localmente; nunca
   commite. Adicione um grep de pré-commit como rede de segurança.

3. **`PYTHONBREAKPOINT=0`** desativa todo `breakpoint()`. Confira a env se o breakpoint não
   estiver disparando:
   ```bash
   echo $PYTHONBREAKPOINT
   ```

4. **`debugpy.listen` só bloqueia se você também chamar `wait_for_client()`.** Sem isso, a
   execução continua e seu primeiro breakpoint pode disparar antes do cliente anexar.

5. **Anexar por PID falha em kernel endurecido.** `ptrace_scope=1` (padrão Ubuntu) só permite
   ptrace de processo filho pelo mesmo usuário. Solução: `echo 0 > /proc/sys/kernel/yama/ptrace_scope`
   (precisa de root) ou lance já sob `debugpy` desde o início.

6. **Threads.** `pdb` só depura a thread atual. Para código multithread, use `debugpy` (DAP
   thread-aware) ou `threading.settrace()` por thread.

7. **asyncio.** `pdb` funciona em coroutine mas `await` dentro do pdb exige Python 3.13+ ou
   `await` via modo `interact` em versões mais antigas. Em 3.11/3.12, use truques com
   `asyncio.run_coroutine_threadsafe` ou `!stmt` com `asyncio.ensure_future`.

8. **Forking / multiprocessing.** pdb não segue fork. Cada filho precisa do próprio
   `breakpoint()` ou `set_trace()`. Depure um processo por vez.

## Checklist de verificação

- [ ] Depois de `pip install debugpy`, confirme: `python -c "import debugpy; print(debugpy.__version__)"`
- [ ] Para debug remoto, confirme que a porta está de fato escutando: `ss -tlnp | grep 5678`
- [ ] O primeiro breakpoint de fato dispara (se não disparar, provavelmente é
  `PYTHONBREAKPOINT=0`, você está sob xdist, ou a execução terminou antes de anexar)
- [ ] `where` / `w` mostra a call stack esperada
- [ ] Limpeza pós-debug: nenhum `breakpoint()` / `set_trace()` perdido no código commitado
  ```bash
  rg -n 'breakpoint\(\)|set_trace\(|debugpy\.listen' --type py
  ```

## Receitas rápidas

**"Por que esse dict tá sem uma chave?"**
```python
# adiciona acima do ponto do KeyError
breakpoint()
# depois no pdb:
(Pdb) pp d
(Pdb) pp list(d.keys())
(Pdb) w                # como chegou aqui
```

**"Esse teste passa isolado mas falha na suíte."**
```bash
uv run pytest tests/o_teste.py --pdb -p no:xdist
# Mas se só falha JUNTO com outros testes:
uv run pytest tests/ -x --pdb -p no:xdist
# Agora ele para no pdb exatamente no teste que falha depois do estado acumular.
```

**"Meu handler async trava (deadlock)."**
```python
# adiciona na entrada do handler
import remote_pdb; remote_pdb.set_trace(host="127.0.0.1", port=4444)
```
Dispara o handler. `nc 127.0.0.1 4444`, depois `w` pra ver o frame suspenso,
`!import asyncio; asyncio.all_tasks()` pra ver o que mais está pendente.

**"Post-mortem num crash de subprocess."**
```bash
PYTHONFAULTHANDLER=1 python -m pdb -c continue caminho/do/entrypoint.py
# No crash, pdb pousa no frame da exceção com todos os locals
```
