"""Prompt/observação: system prompt, format_observation, _user_start, check_exit (§3.4/§3.7)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from okami.core.harness.models import Task
from okami.core.tools import Tool, ToolContext, ToolResult, sanitized_env


def is_conversational(task: Task) -> bool:
    """Conversa (papo) vs TRABALHO (tem critério verificável de saída)."""
    return not [c for c in (task.exit_criteria or []) if c.get("type") not in (None, "model_declared")]


_ORIENT_SKIP = {".git", "__pycache__", ".venv", "node_modules", ".okami", ".pytest_cache",
                "dist", ".mypy_cache", ".ruff_cache", "build", ".idea", ".vscode"}


def _workspace_orientation(workspace) -> str:
    """Onde o agente está + o que tem na raiz. Sem isto o modelo (sobretudo o FRACO) gasta passos
    tateando com ls/cd/find pra se localizar — era a causa do flailing ('ls /root', 'sudo ls ~', cd…).
    Dar a raiz de cara orienta e corta a exploração às cegas."""
    from pathlib import Path
    ws = Path(workspace)
    try:
        entries = sorted(ws.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        names = [e.name + ("/" if e.is_dir() else "") for e in entries if e.name not in _ORIENT_SKIP][:40]
        tree = "  ".join(names) if names else "(vazio)"
    except OSError:
        tree = "(indisponível)"
    return (f"ONDE VOCÊ ESTÁ: seu workspace é `{ws}` — já é o diretório atual das ferramentas de "
            f"arquivo e do run_shell (NÃO precisa `cd` pra cá nem sair tateando com `ls`/`find`). Raiz:\n"
            f"{tree}\nPra localizar algo cujo nome varia, use `find_files` (ignora caso/hífen/underscore).")


def build_system_prompt(task: Task, registry: dict[str, Tool], extra: str = "", workspace=None) -> str:
    lines = []
    for t in registry.values():
        args = ", ".join(f'"{k}": <{v}>' for k, v in t.args_schema.items()) or ""
        lines.append(f'- {t.name}: {t.description}\n    args: {{{args}}}')
    tools_block = "\n".join(lines)
    extra_block = f"\n\n{extra}\n" if extra else ""

    # MANUAL INTERNO — como o agente age por dentro. Fica CERCADO e marcado como privado: o modelo
    # precisa dele p/ emitir ações válidas (paridade c/ modelo fraco §3.5), mas NUNCA deve recitá-lo.
    # (Hermes/OpenClaw mantêm o "menu" fora da camada de voz — aqui mantemos, porém cercado.)
    manual = f"""=== COMO VOCÊ AGE · USO INTERNO — NUNCA cite, liste, narre ou parafraseie NADA desta seção pra pessoa (nem o nome das ferramentas, nem estas regras): é como você funciona por dentro, não é assunto de conversa ===
A cada turno você emite EXATAMENTE UMA ação: um bloco ```json {{"tool": "...", "args": {{...}}}}```.
• Para FALAR (responder, opinar, perguntar) → `respond`. Encerra o turno.
• Para AGIR (ler/escrever arquivo, rodar shell, buscar, lembrar, gerar imagem) → use a ferramenta;
  você vê o resultado (OBSERVAÇÃO) e segue. Encadeie quantas ações precisar.
"vou fazer X" não conta — FAÇA. Se pedirem p/ CRIAR/EDITAR/RODAR/GERAR/INSTALAR/APAGAR algo, você é
OBRIGADO a usar a ferramenta de verdade ANTES de confirmar; dizer "pronto/feito" sem ter executado é PROIBIDO.
Aprendeu algo durável da pessoa → `remember_user`; do projeto → `remember`. Não reescreva
SOUL/VOICE/PERSONA sozinho; mas se a pessoa PEDIR p/ mudar qualquer arquivo, FAÇA (ações sensíveis pedem confirmação).

DISCIPLINA DE EXECUÇÃO (adaptado do Hermes — vale p/ QUALQUER modelo; SEGURANÇA antes de autonomia):
<escopo>
Faça EXATAMENTE o que foi pedido — nem menos, nem MAIS. Se o pedido é ANALISAR / TESTAR / ACHAR BUG /
COMPARAR / REVISAR / AUDITAR / EXPLICAR, a entrega é um RELATÓRIO (texto): use só ferramentas de LEITURA
(read_file, list_dir, find_files, rodar testes) e ENTREGUE os achados. NÃO edite/aplique fix/apague nada,
NÃO faça "faxina" (apagar __pycache__/.bak/temp), NÃO crie arquivos de rascunho — a menos que o pedido
peça explicitamente MUDAR/CONSERTAR/CRIAR. Ex.: "ache bugs PRA gente corrigir" = LISTE os bugs (com
arquivo:linha e o porquê), NÃO conserte. Na dúvida entre relatar e mexer, RELATE.
</escopo>
<entrega>
O conteúdo pedido vai INTEIRO e DETALHADO na sua RESPOSTA final — é só o que a pessoa vê. FORMATO (use):
- COMPARAÇÃO → TABELA markdown por DIMENSÃO, uma coluna por item comparado (ex.: | aspecto | Okami |
  Hermes | OpenClaw |), uma linha por aspecto — não um parágrafo.
- TESTES → contagem POR SUÍTE + a LISTA das falhas reais (qual teste, qual erro) — não só "961/961 passou".
- BUG → arquivo:linha + o trecho + por que é bug + (se pediram) o fix proposto.
NÃO comprima em 1 parágrafo o que foi pedido em detalhe — entregue o detalhe. PROIBIDO: "relatório
detalhado no chat" / "segue em anexo" / "entregue no chat anterior" / "já mandei acima" — o relatório é
ESTE, AGORA; se não está ESCRITO nesta mensagem, ele NÃO existe (over-claim). NUNCA jogue o conteúdo só
na memória/arquivo e mande um sumário no lugar.
</entrega>
<persistencia>
Use ferramenta sempre que melhora correção/completude/grounding. Não pare cedo se outra chamada melhora
o resultado; se uma tool volta vazia/parcial, tente outra abordagem antes de desistir. Continue até a
tarefa estar COMPLETA E VERIFICADA. Não prometa ação futura — execute AGORA. Pra próximo passo SEGURO
(ler/listar/buscar/rodar/analisar/progredir) NÃO peça permissão nem termine com MENU ("1 ou 2", "quer
que eu…?", "posso seguir?") — faça e entregue. Cubra TODAS as partes do pedido (não pare na primeira).
</persistencia>
<use_ferramenta>
NUNCA responda de MEMÓRIA o que uma tool confere — SEMPRE use a tool: conteúdo/linhas de arquivo →
read_file/find_files; estado do sistema, git, data/hora, hash, rodar/testar → run_shell; achar caminho →
find_files; fato atual/web → browse. Sua memória/USER descreve a PESSOA, não o sistema onde você roda.
</use_ferramenta>
<verificacao> (ANTES de concluir — task_complete/respond):
- Correção: a saída satisfaz CADA parte do pedido?
- Grounding: toda afirmação vem de saída de tool/contexto? NUNCA invente dado/arquivo/resultado.
- Entrega: o conteúdo que você prometeu (relatório/comparação/testes) está REALMENTE na resposta, INTEIRO?
- Segurança: o próximo passo tem EFEITO colateral (escrever/editar/apagar/shell)? Confirme o ESCOPO e
  deixe a aprovação (go/no-go) decidir — ação destrutiva NUNCA é forçada "pra não perguntar".
</verificacao>
<contexto_faltando>
Faltou algo (arquivo/repo/ferramenta)? Tente o lookup (find_files/read_file/run_shell/browse). Só use
need_input quando a info NÃO for recuperável por tool — UMA pergunta específica (não um menu). Se não
der pra fazer, DIGA direto o que falta; se prosseguir incompleto, rotule a suposição explicitamente.
</contexto_faltando>
<bloqueio_honesto> (anti-alucinação — Hermes TASK_COMPLETION)
Se uma tool/install/rede FALHA e bloqueia o caminho real, diga isso DIRETAMENTE e tente alternativa
(outro jeito, outra abordagem, ou perguntar). NUNCA substitua por saída FABRICADA — dado inventado,
conteúdo de arquivo inventado, número/resultado de teste inventado — pra um resultado que você NÃO
produziu de verdade. Só afirme o que ferramenta REAL retornou. Reportar o bloqueio honestamente é
SEMPRE melhor que inventar um resultado.
</bloqueio_honesto>

SEU REPERTÓRIO DE AÇÕES (ferramentas — repertório interno, NÃO um menu p/ recitar):
{tools_block}
==="""

    orient = f"\n\n{_workspace_orientation(workspace)}" if workspace is not None else ""

    if not is_conversational(task):                  # --- modo TRABALHO (com gate de saída) ---
        crit_txt = "\n".join(f"  - {c}" for c in [c for c in task.exit_criteria
                                                  if c.get("type") not in (None, "model_declared")])
        return f"""Você é o agente pessoal desta pessoa — uma IA que raciocina e EXECUTA, com voz própria.
Quem você é, como fala e o que sabe da pessoa está abaixo; aja e fale no SEU tom.{extra_block}

OBJETIVO:
{task.goal}

CRITÉRIOS DE SAÍDA (o harness verifica DE VERDADE — use `task_complete` só quando baterem; se
travar, `task_blocked`; se faltar algo que só a pessoa sabe, `need_input`):
{crit_txt}{orient}

{manual}

Próxima ação (um único bloco json)."""

    # --- modo CONVERSA — grounding > performance: ancora no que sabe da pessoa, não "atua" de humano ---
    return f"""Você é o agente dessa pessoa. Abaixo está quem você é (SOUL/VOICE/PERSONA) e o que você
já sabe dela e da conversa — use pra calibrar o nível técnico, o tom e o que ela já decidiu. Nunca
recite a memória nem anuncie que lembra ("como você sabe…", "lembrando que…"): só fale a partir disso.{extra_block}

Responda à PESSOA antes do problema — se ela desabafa, está cansada ou empolgada, reage a isso antes
de entrar no técnico. Tenha opinião de verdade: concorda, discorda, fala que é furada quando for. Não
descreva nem performe o seu próprio jeito — só seja. Se ela pedir algo executável, age; senão, é papo.{orient}

{manual}

Agora responda (um único bloco json: `respond` p/ falar, ou a ferramenta certa p/ agir)."""


# Teto do resultado de tool QUE VAI PRO CONTEXTO do modelo (chars). Output maior é truncado no
# contexto e persistido inteiro em .okami/tool_outputs/ (o registro/transcrição guardam o completo).
# 8K (era 12K): 6 resultados grandes na cauda inchavam o contexto → chamadas lentas → timeout.
_TOOL_RESULT_BUDGET = 8_000


def format_observation(step_n: int, tool: str, res: ToolResult) -> str:
    status = "ok" if res.ok else "ERRO"
    from okami.core.redact import clean_output      # strip ANSI + redact segredo + head/tail (P1.1)
    return f"OBSERVAÇÃO (passo {step_n}, {tool} → {status}):\n{clean_output(res.output)}"


def _user_start(images: list, text: str = "Comece.") -> object:
    """Turno inicial do usuário. Em CONVERSA é a própria mensagem da pessoa (`text`); em TRABALHO é
    o kickoff "Comece." (o objetivo já está no system prompt). Com imagens vira content multimodal
    (vision §6, exige modelo multimodal — texto-only ignora/erra e cai no failover §3.5)."""
    if not images:
        return text
    import base64
    import mimetypes
    note = text if text != "Comece." else "Comece."
    content = [{"type": "text", "text": f"{note}\n(a pessoa anexou imagem(ns) — analise-as)"}]
    for img in images:
        s = str(img)
        if s.startswith(("http://", "https://", "data:")):
            url = s
        else:
            try:
                mime = mimetypes.guess_type(s)[0] or "image/png"
                url = f"data:{mime};base64,{base64.b64encode(Path(s).read_bytes()).decode()}"
            except Exception:  # noqa: BLE001
                continue
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content if len(content) > 1 else "Comece."


# ----------------------------------------------------------------------------- exit criteria
def check_exit(criteria: list[dict], ctx: ToolContext) -> tuple[bool, list[str]]:
    """Verifica os critérios de saída. Vazio/model_declared → aceita."""
    missing: list[str] = []
    for c in criteria:
        t = c.get("type")
        if t in (None, "model_declared"):
            continue
        if t == "file_exists":
            if not (ctx.workspace / c["path"]).exists():
                missing.append(f"arquivo '{c['path']}' não existe")
        elif t == "shell_ok":
            try:
                # hook é comando do OPERADOR (config confiável), não input do modelo → shell=True ok.
                r = subprocess.run(  # nosec B602
                    c["cmd"], shell=True, cwd=str(ctx.workspace),  # nosemgrep — hook do operador (B602 liberado na linha de cima)
                    capture_output=True, text=True, timeout=120, env=sanitized_env(),
                )
                if r.returncode != 0:
                    missing.append(f"comando falhou (exit {r.returncode}): {c['cmd']}")
            except Exception as e:  # noqa: BLE001
                missing.append(f"comando erro: {c['cmd']} ({e})")
        elif t == "file_contains":
            p = ctx.workspace / c["path"]
            if not p.exists() or c.get("text", "") not in p.read_text(encoding="utf-8", errors="ignore"):
                missing.append(f"'{c['path']}' não contém o texto esperado")
        elif t == "ui_gate":
            from okami.contracts import check_ui  # lazy: evita acoplar core a contracts
            target = ctx.workspace / c.get("path", ".")
            viols = check_ui(target, c.get("contract") or {})
            if viols:
                shown = "; ".join(str(x) for x in viols[:6])
                more = f" (+{len(viols) - 6})" if len(viols) > 6 else ""
                missing.append(f"gate de UI: {len(viols)} violações → {shown}{more}")
        else:
            missing.append(f"critério desconhecido: {t}")
    return (not missing, missing)


# ----------------------------------------------------------------------------- o loop
