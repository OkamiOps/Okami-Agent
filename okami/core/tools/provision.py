"""Tools de PROVISÃO REMOTA — o agente bootstrappa o próprio acesso numa VPS limpa (SSH + GitHub),
dirigido pelo dono por um canal. São o caminho SANCIONADO p/ ~/.ssh e git auth (furam o jail
_SENSITIVE_PATH só aqui), danger=dangerous → sempre approval-gated. Segredo NUNCA é repetido na saída.
"""
from __future__ import annotations

import os

from okami.core.tools.base import Tool, ToolResult


class SshIdentity(Tool):
    name = "ssh_identity"
    description = (
        "Gerencia a identidade SSH do agente NESTA máquina (VPS): gerar uma chave, importar uma chave "
        "privada que o dono mandou, mostrar a PÚBLICA (p/ ele colar no GitHub/host), registrar um host "
        "conhecido (ssh-keyscan), ou ver o status. É o jeito CERTO de mexer em ~/.ssh (write_file/run_shell "
        "barram). NUNCA repita o valor de uma chave PRIVADA na resposta — confirme só pelo fingerprint."
    )
    args_schema = {
        "action": "generate | import | show | known_host | status",
        "private_key": "(import) a chave PRIVADA que o dono mandou — gravada 0600; NUNCA é repetida",
        "host": "(known_host) host p/ registrar (ex.: github.com)",
        "name": "(opc) nome do arquivo da chave em ~/.ssh (default id_ed25519)",
    }
    required = ("action",)

    def run(self, args, ctx):
        from okami.core.redact import redact
        from okami.integrations import provision as pr
        action = str(args.get("action") or "").strip().lower()
        name = str(args.get("name") or "id_ed25519").strip() or "id_ed25519"
        try:
            if action == "generate":
                r = pr.generate_ssh_key(name=name)
                head = "🔑 chave gerada" if r["created"] else "🔑 já existia uma chave"
                return ToolResult(True, f"{head} ({r['fingerprint']}).\nAdicione esta chave PÚBLICA no "
                                  f"GitHub (Settings → SSH keys) ou no authorized_keys do host:\n{r['public_key']}",
                                  effect=r["created"])
            if action == "import":
                pk = args.get("private_key")
                if not isinstance(pk, str) or not pk.strip():
                    return ToolResult(False, "ssh_identity import exige 'private_key' (a chave privada). "
                                      "Não vou repetir o valor.", effect=False)
                r = pr.import_private_key(pk, name=name)
                return ToolResult(True, f"🔑 chave privada importada ({r['fingerprint']}, 0600). Pública "
                                  f"derivada:\n{r['public_key']}\n(não repito a privada).", effect=True)
            if action == "show":
                pub = pr.public_key(name)
                return ToolResult(bool(pub), pub or f"não há chave '{name}' em ~/.ssh — gere com "
                                  "action=generate.", effect=False)
            if action == "known_host":
                host = str(args.get("host") or "").strip()
                r = pr.known_host(host)
                return ToolResult(True, f"{'✓ registrado' if r['added'] else 'já estava registrado'} "
                                  f"{r['host']} em known_hosts.", effect=r["added"])
            if action == "status":
                st = pr.git_auth_status()
                keys = ", ".join(f"{k['name']} ({k['fingerprint'].split()[1] if k['fingerprint'] else '?'})"
                                 for k in st["ssh_keys"]) or "(nenhuma)"
                return ToolResult(True, f"chaves SSH em ~/.ssh: {keys}", effect=False)
            return ToolResult(False, "ssh_identity: action deve ser generate|import|show|known_host|status.",
                              effect=False)
        except Exception as e:  # noqa: BLE001 — erro NUNCA carrega material de chave
            return ToolResult(False, f"ssh_identity {action} falhou: {redact(str(e))}", effect=False)


class GitAuth(Tool):
    name = "git_auth"
    description = (
        "Configura o acesso do agente ao GitHub NESTA máquina (VPS). action=token: usa um Personal Access "
        "Token (passe o NOME de um segredo já guardado com store_secret) e configura git de forma file-based "
        "(funciona mesmo com o env sanitizado do shell). action=ssh: faz o git falar SSH (usa a chave do "
        "ssh_identity). action=status/verify: estado e teste de acesso. NUNCA repita o token na resposta."
    )
    args_schema = {
        "action": "token | ssh | status | verify",
        "secret": "(token) NOME de um segredo já guardado (ex.: GITHUB_TOKEN) — recomendado",
        "token": "(token) alternativa: o PAT literal (menos seguro que 'secret')",
        "user_name": "(opc) git user.name p/ os commits",
        "user_email": "(opc) git user.email p/ os commits",
        "host": "(opc) default github.com",
    }
    required = ("action",)

    def run(self, args, ctx):
        from okami.core.redact import redact
        from okami.integrations import provision as pr
        action = str(args.get("action") or "").strip().lower()
        host = str(args.get("host") or "github.com").strip() or "github.com"
        try:
            if action == "token":
                secret_name = str(args.get("secret") or "").strip()
                token = os.environ.get(secret_name) if secret_name else None
                if not token:
                    token = args.get("token") if isinstance(args.get("token"), str) else None
                if not token:
                    return ToolResult(False, "git_auth token: passe 'secret' (nome de um segredo já guardado "
                                      "com store_secret, ex.: GITHUB_TOKEN) ou 'token' (o PAT). Não vou imprimir "
                                      "o valor.", effect=False)
                r = pr.configure_git_token(token, user_name=str(args.get("user_name") or ""),
                                           user_email=str(args.get("user_email") or ""), host=host)
                who = f" como {r['user_name']}" if r.get("user_name") else ""
                return ToolResult(True, f"✓ git configurado p/ {host} via token (file-based{who}). "
                                  "`git push`/`gh` já funcionam. Não repito o token.", effect=True)
            if action == "ssh":
                pr.configure_git_ssh(host=host)
                return ToolResult(True, f"✓ git agora fala SSH com {host} (usa a chave do ssh_identity). "
                                  f"Garanta que a pública está no GitHub e rode action=verify.", effect=True)
            if action == "status":
                st = pr.git_auth_status()
                return ToolResult(True, f"GitHub auth — token p/ hosts: {st['token_hosts'] or '(nenhum)'} · "
                                  f"user: {st['user_name'] or '?'} <{st['user_email'] or '?'}> · "
                                  f"chaves SSH: {len(st['ssh_keys'])}", effect=False)
            if action == "verify":
                r = pr.verify(host=host)
                return ToolResult(r["ssh_ok"], ("✓ SSH autenticado no " + host if r["ssh_ok"]
                                  else "SSH ainda não autenticou: ") + ("" if r["ssh_ok"] else r["ssh_msg"]),
                                  effect=False)
            return ToolResult(False, "git_auth: action deve ser token|ssh|status|verify.", effect=False)
        except Exception as e:  # noqa: BLE001 — erro NUNCA carrega o token
            return ToolResult(False, f"git_auth {action} falhou: {redact(str(e))}", effect=False)
