---
name: docker-ops
description: Gerencia Docker na VPS — ciclo de vida de container, Compose, volumes/redes, limpeza de disco — e ergonomia geral de linha de comando.
triggers: [docker, compose, container, dockerfile, docker-compose, imagem docker, volume, subir o container, daemon do docker]
intent_examples:
  - "sobe os containers do compose"
  - "por que esse container fica reiniciando"
  - "o docker tá reclamando de espaço em disco"
  - "dá uma limpada nas imagens não usadas"
  - "entra no container e olha o log"
metadata:
  hermes:
    tags: [docker, containers, devops, infrastructure, compose, images, volumes, networks, debugging, cli]
    category: devops
    related_skills: [acesso-vps]
---
# Docker + ergonomia de CLI

Gerencia containers, imagens, volumes, redes e stacks Compose com o CLI padrão do Docker via
`run_shell`. Nenhuma dependência além do próprio Docker.

## Quando usar

- Rodar, parar, reiniciar, remover ou inspecionar container.
- Buildar, puxar, enviar, taguear ou limpar imagem.
- Trabalhar com Docker Compose (stack multi-serviço).
- Gerenciar volume ou rede.
- Depurar container que crasha ou analisar log.
- Checar uso de disco do Docker ou liberar espaço.
- Revisar/otimizar um Dockerfile.

## Antes de qualquer coisa: o daemon está de pé?

Essa é a causa nº 1 de um shell que "trava" nesta skill: rodar `docker ...` numa VPS onde o
daemon não está no ar deixa o comando pendurado esperando o socket, em vez de falhar rápido. Rode
o diagnóstico desta skill primeiro:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/docker_daemon_check.py
```

Devolve JSON (`cli`, `daemon_up`, `compose_v2`, `hint`) e exit code 0 só quando dá pra prosseguir
com segurança. Se `daemon_up` vier `false`, siga o `hint` (systemd em VPS Linux: `sudo systemctl
start docker`; Docker Desktop/Colima local: suba o app antes de tentar de novo) — **não** fique
repetindo o mesmo comando `docker` esperando que ele "acorde" sozinho.

Checagem manual equivalente, se preferir:
```bash
docker --version && docker compose version && docker info --format '{{.ServerVersion}}'
```

## Referência rápida

| Tarefa | Comando |
|---|---|
| Rodar container (background) | `docker run -d --name NOME IMAGEM` |
| Parar + remover | `docker stop NOME && docker rm NOME` |
| Ver log (seguindo) | `docker logs --tail 50 -f NOME` |
| Shell dentro do container | `docker exec -it NOME /bin/sh` |
| Listar todos os containers | `docker ps -a` |
| Buildar imagem | `docker build -t TAG .` |
| Compose up | `docker compose up -d` |
| Compose down | `docker compose down` |
| Uso de disco | `docker system df` |
| Limpeza de itens soltos | `docker container prune && docker image prune` |

## Ciclo de vida de container

```bash
# Serviço em background com porta mapeada
docker run -d --name web -p 8080:80 nginx

# Com variável de ambiente
docker run -d -e POSTGRES_PASSWORD=mude-isto -e POSTGRES_DB=meubanco --name db postgres:16

# Com dado persistente (volume nomeado)
docker run -d -v pgdata:/var/lib/postgresql/data --name db postgres:16

# Desenvolvimento (bind mount do código fonte)
docker run -d -v $(pwd)/src:/app/src -p 3000:3000 --name dev minha-app

# Depuração interativa (auto-remove ao sair)
docker run -it --rm ubuntu:22.04 /bin/bash

# Com limite de recurso e política de restart
docker run -d --memory=512m --cpus=1.5 --restart=unless-stopped --name app minha-app
```

Flags principais: `-d` desanexado, `-it` interativo+tty, `--rm` auto-remove, `-p` porta
(host:container), `-e` variável de ambiente, `-v` volume, `--name` nome, `--restart` política.

```bash
docker ps                        # containers rodando
docker ps -a                     # todos (incluindo parados)
docker stop NOME                 # para graciosamente
docker restart NOME              # para + inicia
docker rm -f NOME                # remove à força mesmo rodando
docker container prune           # remove TODOS os parados

docker exec -it NOME /bin/sh          # shell (use /bin/bash se disponível)
docker exec -u root NOME apt update    # roda como usuário específico
docker logs --since 2h NOME            # log das últimas 2 horas
docker cp NOME:/caminho/arquivo ./local
docker inspect NOME | python3 -m json.tool   # detalhe completo, formatado
docker stats --no-stream               # snapshot de uso de recurso
```

## Imagens

```bash
docker build -t minha-app:latest .
docker build --no-cache -t minha-app .              # rebuild limpo
DOCKER_BUILDKIT=1 docker build -t minha-app .        # mais rápido, com BuildKit

docker images                          # imagens locais
docker history IMAGEM                  # camadas
docker image prune                     # remove imagens soltas (sem tag)
docker image prune -a --filter "until=168h"   # não usadas há mais de 7 dias
```

## Docker Compose

```bash
docker compose up -d                   # sobe tudo em background
docker compose up -d --build           # rebuilda antes de subir
docker compose down                    # para e remove containers
docker compose down -v                 # também remove volumes (DESTRÓI DADO — confirme com o dono)

docker compose ps                      # lista serviços
docker compose logs -f api             # segue log de um serviço
docker compose exec api /bin/sh        # shell num serviço rodando
docker compose run --rm api npm test   # comando avulso (container novo)
docker compose config                  # valida e mostra config resolvida
```

Compose mínimo:
```yaml
services:
  api:
    build: .
    ports: ["3000:3000"]
    environment:
      - DATABASE_URL=postgres://usuario:mude-isto@db:5432/meubanco
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: usuario
      POSTGRES_PASSWORD: mude-isto
      POSTGRES_DB: meubanco
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U usuario"]
      interval: 10s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
```

## Volumes e redes

```bash
docker volume ls / create NOME / inspect NOME / rm NOME / prune
docker network ls / create NOME / inspect NOME / rm NOME / prune
docker network connect/disconnect NOME_REDE NOME_CONTAINER
```

## Disco e limpeza

Sempre diagnostique antes de limpar:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/docker_disk_report.py            # relatório (docker system df -v)
python3 ${OKAMI_SKILL_DIR}/scripts/docker_disk_report.py --apply-safe  # + prune de container/image/network
```

`--apply-safe` nunca toca em volume nomeado nem roda `system prune -a --volumes`. Isso — a limpeza
agressiva que apaga volume nomeado — só roda com confirmação explícita do dono:

```bash
docker system prune -a --volumes   # TUDO, incluindo volume nomeado — confirme antes
```

## Pegadinhas

| Problema | Causa | Correção |
|---|---|---|
| Comando `docker` trava sem erro | Daemon fora do ar, comando espera o socket | Rode `docker_daemon_check.py` ANTES de qualquer sequência de comando |
| Container sai na hora | Processo principal terminou/crashou | `docker logs NOME`; `docker run -it --entrypoint /bin/sh IMAGEM` pra investigar |
| "port is already allocated" | Outro processo já usa a porta | `docker ps` ou `lsof -i :PORTA` pra achar quem |
| "no space left on device" | Disco do Docker cheio | `docker system df` → limpeza direcionada com o script acima |
| Não conecta no container | App escuta em `127.0.0.1` dentro do container | App precisa escutar em `0.0.0.0`; confira o `-p` |
| Serviços do Compose não se acham | Rede ou nome de serviço errado | Serviço usa o nome do serviço como hostname; `docker compose config` |
| Cache de build não funciona | Ordem de camada errada no Dockerfile | Dependência antes do código fonte |
| Imagem gigante | Sem multi-stage, sem `.dockerignore` | Multi-stage build + `.dockerignore` |

**Aviso**: nunca rode `docker system prune -a --volumes` sem confirmar com o dono — apaga volume
nomeado com dado potencialmente importante.

## Verificação

Depois de qualquer operação, confirme o resultado:
- Container subiu? → `docker ps` (status "Up")
- Log limpo? → `docker logs --tail 20 NOME`
- Porta acessível? → `docker port NOME` ou `nc -z localhost PORTA`
- Imagem buildou? → `docker images | grep TAG`
- Stack do Compose saudável? → `docker compose ps` (tudo "running"/"healthy")
- Espaço liberado? → `docker system df` antes/depois

## Dockerfile: pontos de otimização

Ao revisar ou criar um Dockerfile, sugira:
1. **Multi-stage build** — separa ambiente de build do runtime, reduz o tamanho final.
2. **Ordem de camada** — dependência antes do código fonte, pra não invalidar cache à toa.
3. **Combinar `RUN`** — menos camadas, imagem menor.
4. **`.dockerignore`** — exclui `node_modules`, `.git`, `__pycache__`, etc.
5. **Fixar versão da imagem base** — `node:20-alpine`, nunca `node:latest`.
6. **`USER` não-root** — segurança.
7. **Base slim/alpine** — `python:3.12-slim` em vez de `python:3.12`.

## Ergonomia geral de linha de comando

- `set -e` em script shell — para no primeiro comando que falhar, em vez de continuar cego.
- Sempre confira `$?` (ou o exit code que `run_shell` devolve) antes de anunciar sucesso — um
  comando pode imprimir algo plausível e ainda ter saído com erro.
- Prefira `--format`/`--no-trunc` do Docker a `grep`/`cut` frágil quando o comando já oferece
  saída estruturada (`docker ps --format '{{.Names}}\t{{.Status}}'`).
- Pipe pra `python3 -m json.tool` (stdlib, sem instalar `jq`) pra formatar JSON de saída.
- Comando longo/interativo que não pode bloquear o turno inteiro → tool `process_start` (com
  `process_poll`/`process_log` pra acompanhar), não `run_shell` puro.
- Sempre aspas duplas em variável que pode ter espaço/glob (`"$VAR"`, não `$VAR`), evita
  word-splitting silencioso.
- Antes de repetir um comando que falhou torcendo pra dar certo, leia a mensagem de erro
  completa — geralmente ela já diz a causa raiz.

## Relacionado

- `acesso-vps` — bootstrap de acesso (GitHub/SSH) numa VPS limpa
- `api-debug` — quando o que está travando é uma chamada HTTP, não o Docker em si
