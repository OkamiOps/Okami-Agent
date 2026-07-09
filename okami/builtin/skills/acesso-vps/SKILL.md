---
name: acesso-vps
description: Bootstrappar acesso (GitHub/SSH) numa VPS limpa — sem depender da máquina do dono. Token ou chave SSH.
triggers: [git push, gh, clone, github, ssh, permission denied, could not read from remote, autenticar, deploy, vps, servidor]
intent_examples:
  - "faz push disso pro github"
  - "clona meu repositório privado"
  - "conecta no meu outro servidor por ssh"
  - "deu permission denied no git"
---
# Acessar GitHub e outros hosts (VPS-first)

Você roda numa VPS 24/7 — **não tem acesso à máquina do dono**. Numa VPS limpa NÃO existe login do
`gh`/`git` herdado nem chave SSH. Quando um `git push`/`clone` ou um SSH falhar por autenticação, **não
desista**: você bootstrappa o próprio acesso com as tools sancionadas, guiando o dono pelo canal.

Essas tools (`ssh_identity`, `git_auth`) são o jeito CERTO de mexer em `~/.ssh` e na auth do git — o
`write_file`/`run_shell` barram esses caminhos de propósito. Elas pedem aprovação. NUNCA repita o valor
de um token ou de uma chave privada na resposta.

## GitHub por TOKEN (HTTPS) — mais simples
1. Peça ao dono um Personal Access Token (GitHub → Settings → Developer settings → Tokens) com escopo `repo`.
2. Quando ele mandar, guarde com `store_secret` (ex.: nome `GITHUB_TOKEN`) — o valor não vai pro histórico.
3. Rode `git_auth` action=token, passando `secret=GITHUB_TOKEN` (+ `user_name`/`user_email` p/ os commits).
   Isso configura o git de forma file-based — funciona mesmo com o ambiente do shell sanitizado.
4. Agora `git clone/push https://github.com/...` e o `gh` funcionam.

## GitHub por CHAVE SSH — bom p/ acesso duradouro
1. Rode `ssh_identity` action=generate. A chave PRIVADA fica só na VPS; você recebe a PÚBLICA.
2. Mostre a pública ao dono e peça pra ele adicionar em GitHub → Settings → SSH and GPG keys (ou como
   deploy key no repositório). Se ele já tiver uma chave e preferir mandar a privada, use action=import.
3. Rode `git_auth` action=ssh (faz o git falar SSH com o github.com usando a chave).
4. Confirme com `git_auth` action=verify — sucesso é o GitHub dizendo "successfully authenticated".

## SSH para outros servidores do dono
1. Garanta uma chave com `ssh_identity` action=generate (ou show, se já existe).
2. Peça ao dono pra pôr a sua PÚBLICA no `~/.ssh/authorized_keys` do servidor-alvo.
3. Registre o host com `ssh_identity` action=known_host (evita o prompt de fingerprint).
4. Use `remote_connect` pro alias/host e seus comandos passam a rodar lá.

## Lembre
- Prefira GERAR a chave na VPS (a privada nunca sai) a importar uma chave que o dono digita no chat.
- Se faltar permissão pra rodar a tool, é o grant de shell/provisão — peça ao dono pra liberar.
- `git_auth` action=status mostra o estado atual sem revelar segredo nenhum.
- Credencial faltando é sempre um PEDIDO ao dono pelo canal seguro (`store_secret`) — nunca
  vasculhe o disco atrás de token/chave/cookie de outra ferramenta, e nunca proponha `--yolo` ou
  qualquer bypass de sandbox pra contornar a falta de acesso. Veja `ferramentas-nativas-primeiro`.
