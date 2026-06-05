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
| `retention.require`                     | sem retenção/quota declarada → aviso (configure a limpeza)    |
| `gateway.require_token` / `forbid_public_bind` | API sem `OKAMI_API_TOKEN` ou bind `0.0.0.0` → falha   |
| `channels.forbid_open_ingress`          | `allow_all: true` (ingress aberto) → falha                   |
| `mcp.max_trust: reviewed`               | servidor MCP `trusted` (bypassa o gate) → falha              |

## 2. Ative o isolamento estrito no runtime

No `okami.yaml` (ou `okami.local.yaml`) do ambiente de produção:

```yaml
sandbox:
  require_isolation: true     # ou: profile: hardened-strict
  # exposto + sem Docker → run_shell/process_start DESABILITADOS (exit 126), não caem no local
```

Com Docker presente, a superfície exposta roda isolada (rede off, não-root, `--cap-drop ALL`,
rootfs read-only, só o workspace montado). Sem Docker, recusa — fail-closed.

## 3. Checklist de GA

- [ ] `okami policy check --strict` passa (0 FAIL).
- [ ] `sandbox.require_isolation: true` no ambiente exposto, com Docker disponível.
- [ ] Canais com `allow_chats` (deny-by-default) — nunca `allow_all: true`.
- [ ] API com `OKAMI_API_TOKEN` e bind em `127.0.0.1` atrás de proxy/rede privada.
- [ ] Segredos só em `.env` (`${ENV}` no YAML) — `okami doctor --lint` limpo.
- [ ] MCP de terceiro com `trust: reviewed` + manifesto por-tool (nunca `trusted` cego).
- [ ] Retenção/limpeza agendada (`okami clean --deep` no cron) ou bloco `retention:`.
- [ ] CI verde nos gates (ruff, bandit HIGH, pip-audit, secret-scan, `policy check`, CodeQL).

Enquanto o `require_isolation_on_exposed` do `okami.policy.yaml` versionado seguir `false`, o projeto
está em modo **dogfood** — o que é o certo para agora. O `--strict` é o caminho para GA sem mexer no
default de desenvolvimento.
