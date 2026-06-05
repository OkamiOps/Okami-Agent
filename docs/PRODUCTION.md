# Produção / GA — postura para deploy público

O default do Okami é **dogfood/dev-friendly** de propósito: na sua máquina, sem Docker, nada quebra
(`sandbox` cai no backend local, `okami.policy.yaml` traz `require_isolation_on_exposed: false`).
Isso é correto para desenvolver — mas **não** é a postura de um agente exposto à internet.

Para um deploy **público/hostil (GA)**, a postura muda: superfície exposta (Telegram/Slack/Discord/
Mattermost/API/gateway) deve rodar com **isolamento real** (Docker) — e, sem Docker, o shell/process
fica **desabilitado** em vez de degradar para o host.

## 1. Verifique a prontidão de GA (gate)

```bash
okami policy check --strict        # aplica o overlay de PRODUÇÃO sobre a sua policy
okami policy check --strict --json # artefato de conformance p/ CI/pre-deploy
```

O `--strict` (overlay `PRODUCTION_OVERLAY`) endurece:

| regra                                   | efeito em produção                                            |
|-----------------------------------------|--------------------------------------------------------------|
| `sandbox.require_isolation_on_exposed`  | exposto **sem** isolamento real → **FAIL**                   |
| `retention.require`                     | sem retenção/quota declarada → **FAIL** (disco incha)        |
| `gateway.require_token` / `forbid_public_bind` | API sem `OKAMI_API_TOKEN` ou bind `0.0.0.0` → falha   |
| `channels.forbid_open_ingress`          | `allow_all: true` (ingress aberto) → falha                   |
| `mcp.max_trust: reviewed`               | servidor MCP `trusted` (bypassa o gate) → falha              |

No CI, o workflow `production-conformance.yml` roda o `--strict` em **dois modos**: informativo
(cron semanal / dispatch comum) e **bloqueante** (push de tag `v*` ou `workflow_dispatch` com
`enforce=true`) — o release público só passa se a postura estiver conforme.

## 2. Ative o isolamento estrito no runtime

Atalho (escreve no `okami.local.yaml`):

```bash
okami harden          # aplica o perfil hardened-strict (a postura pública/GA)  ·  reverter: okami harden --off
```

Ou na mão, no `okami.yaml` / `okami.local.yaml` do ambiente de produção:

```yaml
sandbox:
  profile: hardened-strict    # perfil NOMEADO p/ GA (equiv. a require_isolation: true, e o que o --strict aceita)
  # exposto + sem Docker → run_shell/process_start DESABILITADOS (exit 126), não caem no local
```

> Sem isso, ao subir `okami gateway` expondo um canal SEM isolamento real, o gateway **avisa de forma
> gritante** no boot (run_shell/process rodam no host). Para dev/testers controlados, ok; para
> "qualquer um manda mensagem", ligue o `okami harden`.

Com Docker presente, a superfície exposta roda isolada (rede off, não-root, `--cap-drop ALL`,
rootfs read-only, só o workspace montado). Sem Docker, recusa — fail-closed.

## 3. Retenção/quota de disco (OBRIGATÓRIA p/ gateway long-running)

Um gateway que roda por semanas incha o disco em `.okami/tool_outputs`, `sessions`/`groups`,
`checkpoints`, `processes` e cache de voz. **Declare** a retenção no `okami.yaml` e **operacionalize**
com um timer — só ter o comando disponível não basta (no `--strict`, retenção ausente é **FAIL**).

```yaml
retention:
  sessions:     {days: 30, keep: 10}
  checkpoints:  {days: 14, keep: 50}
  tool_outputs: {days: 7,  keep: 200}
  processes:    {ttl_hours: 24}
  quota_mb:     {tool_outputs: 500, checkpoints: 200}   # >0 = aviso no status/doctor
```

Agende a poda (escolha um):

```cron
# crontab — poda diária às 04:00 (use --dry-run --json p/ auditar antes)
0 4 * * *  cd /srv/okami && okami clean --deep >> /var/log/okami-clean.log 2>&1
```

```ini
# systemd timer — /etc/systemd/system/okami-clean.{service,timer}
# [Service] ExecStart=/usr/local/bin/okami clean --deep
# [Timer]   OnCalendar=daily   Persistent=true
```

Confira o uso a qualquer momento: `okami status` / `okami doctor` mostram a seção **◆ Disco** (uso
por área + aviso de quota estourada); `okami clean --deep --dry-run --json` audita sem apagar.

## 4. Checklist de GA

- [ ] `okami policy check --strict` passa (0 FAIL).
- [ ] `sandbox.profile: hardened-strict` (via `okami harden`) no ambiente exposto, com Docker disponível.
- [ ] Canais com `allow_chats` (deny-by-default) — nunca `allow_all: true`.
- [ ] API com `OKAMI_API_TOKEN` e bind em `127.0.0.1` atrás de proxy/rede privada.
- [ ] Segredos só em `.env` (`${ENV}` no YAML) — `okami doctor --lint` limpo.
- [ ] MCP de terceiro com `trust: reviewed` + manifesto por-tool (nunca `trusted` cego).
- [ ] Bloco `retention:` declarado **e** `okami clean --deep` agendado (cron/systemd timer).
- [ ] CI verde nos gates (ruff, bandit HIGH, pip-audit, secret-scan, `policy check`, Semgrep).

Enquanto o `require_isolation_on_exposed` do `okami.policy.yaml` versionado seguir `false`, o projeto
está em modo **dogfood** — o que é o certo para agora. O `--strict` é o caminho para GA sem mexer no
default de desenvolvimento.
