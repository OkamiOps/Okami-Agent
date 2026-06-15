# Ambiente remoto (Tailscale SSH) — design

**Data:** 2026-06-14 · **Status:** aprovado p/ planejamento · **Autor:** Marcos + Okami(Claude)

## Problema

O Marcos opera muito via **SSH + Tailscale** (como faz com o hermes-agent): precisa que o agente
acesse outras máquinas, faça configurações, ajuste, publique código e use GitHub. Hoje isso **não
funciona de fato** no Okami, e a investigação (systematic-debugging) mostrou por quê:

1. **Não existe tool/ambiente remoto** — só `run_shell` local.
2. **`sanitized_env()` remove `SSH_AUTH_SOCK`** (casa o padrão `AUTH` em `_SENSITIVE_ENV`) → mesmo que
   o agente rode `ssh` no `run_shell`, a autenticação por ssh-agent quebra. Idem `GH_TOKEN`/`GITHUB_TOKEN`
   (casam `TOKEN`) → `gh`/push por token quebram.
3. **`_SENSITIVE_PATH` bloqueia** comandos com `.ssh`/`id_rsa`/`id_ed25519` → `ssh -i ~/.ssh/key` é
   barrado (mas `ssh user@host "cmd"` puro NÃO é).
4. O agente não tem como saber que pode fazer isso (sem guia, sem lista de hosts).

Resultado: o Marcos viu "ssh não está na lista" e o agente, sem caminho, não opera remotamente.

## Decisões (definidas no brainstorming)

| Decisão | Escolha |
|---|---|
| Superfície | **Os dois** (terminal/TUI + Telegram) → postura forte por padrão |
| Auth | **Tailscale SSH primário + ssh-agent fallback** (opt-in) |
| Formato | **Ambiente remoto completo** (read/write/edit/shell rodam NA máquina remota) |
| Allowlist de host | **Obrigatória no remoto (Telegram/etc.); livre no terminal** |
| Aprovação de conexão | **Nunca** (conecta direto se permitido) |

## Objetivos / Não-objetivos

**Objetivos:** o agente "entra" num host (nó Tailscale ou `user@host`) e suas tools de arquivo+shell
passam a operar lá; `git`/`gh` funcionam (local e remoto); segurança forte por padrão no canal remoto.

**Não-objetivos (YAGNI):** ProxyJump multi-hop; bulk-download em massa; reescrever todas as tools num
ABC `BaseEnvironment` como o Hermes (o branch aditivo é mais simples e mais seguro nos 1984 testes);
montar FS remoto (sshfs); porta-encaminhamento/túnel.

## Arquitetura — a "costura"

Hoje: tools de arquivo resolvem caminho com `_safe_path(ctx, rel)` (local) e o shell roda via
`run_sandboxed(cmd, ctx.workspace)`. Introduzimos um **alvo de execução** ADITIVO, sem reescrever as
tools:

- `ToolContext.remote: RemoteTarget | None = None` → `None` = local, **comportamento atual intacto**.
- `ToolContext.surface: str = "cli"` (novo; `run_task` já tem `surface`) → distingue terminal de remoto
  p/ a regra de allowlist.
- Cada tool de FS + `run_shell` ganha UM branch no topo: `if ctx.remote is not None: return
  self._remote(ctx, ...)`; senão segue o caminho local de hoje. Aditivo → os ~1984 testes que não usam
  remoto batem no `else` e seguem verdes.
- `RemoteTarget` encapsula o host e expõe os primitivos que as tools chamam:
  `run(cmd) · read(path) · write(path, content) · list(path) · exists(path) · mkdir(path) · delete(path)`.

### RemoteTarget (`okami/integrations/remote.py`)

- Campos: `alias`, `host`, `via` (`tailscale`|`ssh`), `cwd`, `control_socket` (path estável p/ ControlMaster).
- Monta o comando base como o Hermes (`_build_ssh_command`):
  - `via=tailscale`: `tailscale ssh <host> -- bash -lc '<cmd>'`.
  - `via=ssh`: `ssh -o ControlPath=<sock> -o ControlMaster=auto -o ControlPersist=300 -o BatchMode=yes
    -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 <host> bash -lc '<cmd>'`.
  - **ControlMaster** reusa a conexão entre chamadas (rápido). `tailscale ssh` herda o multiplexing do
    próprio tailscale; o ControlPath só entra no caminho `ssh` puro.
- Primitivos:
  - `run(cmd)` → executa via base-cmd; devolve `(exit, stdout)` com o mesmo teto/redact do `run_sandboxed`.
  - `read(path)` → `cat -- <path>` (com teto de tamanho); `write(path, content)` → `tee -- <path>` por
    stdin (atômico via `mktemp && mv` remoto p/ não deixar arquivo meia-escrito); `list/exists/mkdir/delete`
    → `ls`/`test`/`mkdir -p`/`rm` (delete remoto vai p/ lixeira remota `~/.okami/trash`, espelhando o local).
- `subprocess` injetável (`runner=subprocess.run` por padrão) → testes sem rede.
- `aclose()` fecha o ControlMaster (`ssh -O exit`).

### Switch — conectar/desconectar

- Tools novas: `remote_connect(host)` e `remote_disconnect()`.
  - `remote_connect` resolve `host`:
    - se casa um alias em `remote.hosts` → usa a config do alias.
    - se é um host cru (`user@maquina` / nome tailscale) → **só permitido em superfície de terminal**
      (`ctx.surface not in _REMOTE_SURFACES`); em superfície remota, host fora da allowlist é **recusado**.
  - seta `session.remote = RemoteTarget(...)`; **sem aprovação** (decisão).
  - faz um *health check* (`run("echo ok")`); falhou → erro claro, não conecta.
- `remote_disconnect()` fecha o ControlMaster e zera `session.remote`.
- Comando `/remote <alias|host>` e `/remote off` (TUI + Telegram), além das tools (p/ o agente agir sozinho).
- O alvo vive na **Session** (sobrevive aos turnos); `run_task` injeta `session.remote` no `ToolContext`.
  O status/loop mostra `📡 <alias>` quando conectado.

### Config (allowlist)

```yaml
remote:
  hosts:
    prod: { host: prod-server, via: tailscale, cwd: /srv/app }
    nas:  { host: deploy@10.0.0.5, via: ssh }
  ssh_agent: true        # opt-in: passa SSH_AUTH_SOCK só pro fallback ssh (default false = removido)
```

- `okami remote add <alias> <host> [--ssh] [--cwd P]` / `okami remote list` / `okami remote remove <alias>`.
- A allowlist é o controle de "quais máquinas" no canal remoto.

## Segurança (postura forte por padrão — "os dois")

- **Allowlist obrigatória no remoto**: em `_REMOTE_SURFACES` (telegram/group/slack/discord/mattermost/api)
  o agente só conecta a alias de `remote.hosts`; host cru é recusado. No terminal (você presente) é livre.
- **Aprovação preservada**: comando remoto que altera estado (`shell_has_effect`) continua passando pelo
  go/no-go; **hardline** (`detect_hardline` — rm de sistema, mkfs, etc.) bloqueia **mesmo remoto**, antes de
  sair pela rede.
- **Jail remoto**: `_SENSITIVE_PATH` vale nos paths remotos (não lê `.env`/`.ssh`/`.aws` da máquina remota
  fora de yolo). Read/write/delete remotos passam pela mesma checagem dos locais.
- **Owner-only**: Telegram já é deny-by-default + `allow_chats`; conectar+operar remoto só p/ quem o canal
  libera. Sem novo vetor de acesso.
- **Auth**: `tailscale ssh` usa a ACL do Tailscale (sem chave gerida). `remote.ssh_agent: true` (opt-in)
  passa `SSH_AUTH_SOCK` ao ambiente do `ssh` fallback; sem opt-in, segue removido (default seguro).
- **Sem novo bypass de segredo**: o RemoteTarget NÃO lê chave nem injeta credencial — delega ao
  `tailscale`/`ssh` do sistema (que já têm a identidade do dono).

## GitHub / publicar código

Cai de graça: com shell (local OU remoto) o agente roda `git`/`gh`. Para o push **local** funcionar
mesmo com a sanitização de env:
- opt-in `tools.env_passthrough: [GH_TOKEN, SSH_AUTH_SOCK]` (reusa o mecanismo que o MCP já tem) →
  `run_sandboxed` repassa SÓ as vars listadas, por nome. Sem opt-in, seguem removidas.
- `gh` autenticado (`~/.config/gh/hosts.yml`) já sobrevive via `HOME` (não é segredo de env).

## Testes

`subprocess` mockado (sem rede):
- `RemoteTarget.run/read/write/list` montam o `tailscale ssh <host> -- bash -lc '<cmd>'` (e a variante
  `ssh` com os `-o ControlMaster/ControlPersist/BatchMode/StrictHostKeyChecking`) corretos.
- `write` é atômico remoto (mktemp+mv); `read` respeita teto; `delete` vai p/ lixeira remota.
- `remote_connect`: alias allowlisted resolve; host cru recusado em superfície remota, aceito no terminal;
  health-check falho não conecta.
- Roteamento: com `ctx.remote` setado, `run_shell`/`read_file`/`write_file`/`edit_file`/`list_dir`
  chamam o RemoteTarget (mock) em vez do FS local; com `ctx.remote=None` o comportamento é idêntico ao de
  hoje (regressão).
- Segurança: hardline remoto bloqueado; `_SENSITIVE_PATH` remoto bloqueado; aprovação disparada p/ comando
  destrutivo remoto.
- `env_passthrough`: só as vars listadas passam.
- Casos com host/tailscale REAL → `@pytest.mark.skipif` (sem binário/rede no CI).

## Fases (cada uma = 1 commit verde, gates: pytest/ruff/bandit/secret-scan)

1. **Núcleo + shell remoto** — `RemoteTarget` (run), config `remote.hosts` + `okami remote`,
   `ToolContext.remote/surface`, `remote_connect/disconnect` (tools + `/remote`), `run_shell` roteado,
   segurança (allowlist-no-remoto, hardline/approval/jail remotos). **Já cobre acessar/configurar/ajustar/
   publicar via shell + GitHub.**
2. **Paridade FS** — `read/write/edit/list/find` remotos (cat/tee/ls/find), delete→lixeira remota.
3. **Acabamento** — status `📡` no loop/TUI, `okami remote` polido, `env_passthrough` p/ push local,
   guia no system prompt ("conectado a <host>: suas tools operam LÁ").

## Riscos / mitigações

- **Refactor das tools de FS (fase 2)** toca arquivos quentes (files.py/patch.py) — mitiga com o branch
  aditivo (local intacto) + testes de regressão `ctx.remote=None`.
- **`tailscale ssh` x ControlMaster** — o multiplexing é do tailscale; ControlPath só no `ssh` puro (já no
  design). Health-check no connect pega config errada cedo.
- **Quoting de comando** (`bash -lc '<cmd>'` com aspas no cmd) — usar `shlex.quote`/heredoc; teste com
  comando que tem aspas/`$`.
