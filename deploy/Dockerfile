# Okami Agent — imagem Linux (também resolve o long-path do Windows ao desenvolver em container).
#
# Multi-stage: o estágio `build` resolve as deps via `uv sync --frozen` (uv.lock travado → build
# REPRODUTÍVEL, mesma versão hoje e daqui 6 meses — ao contrário do antigo `pip install -e ".[dev]"`
# sem lock, que resolvia "o que estiver disponível agora no PyPI" a cada build). O estágio `runtime`
# copia só o venv resolvido + o código — sem toolchain de build, imagem final menor.
FROM python:3.12-slim-bookworm AS build

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Pinado na mesma faixa do uv.lock/dev (ver `uv --version` local) — troque junto se subir o uv do time.
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

WORKDIR /app

# Deps primeiro (cache de camada) — só reprocessa se pyproject.toml/uv.lock mudarem.
# `--extra dev` mantém pytest/ruff/bandit na imagem: é o que `make docker-test` /
# `docker run --rm --entrypoint python okami-agent -m pytest -q` esperam encontrar.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra dev --no-install-project

COPY okami ./okami
COPY tests ./tests
COPY okami.yaml ./
RUN uv sync --frozen --extra dev

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/app/.venv/bin:${PATH}" \
    OKAMI_HOME=/data

WORKDIR /app

# Não-root: o processo do Okami roda como `okami` (uid 10000), não root. $OKAMI_HOME (/data) é o
# volume gravável — o resto da imagem (/app) fica read-only pro usuário de runtime.
RUN groupadd -g 10000 okami && useradd -u 10000 -g okami -m -d /data okami \
 && mkdir -p /data && chown -R okami:okami /data

COPY --from=build --chown=okami:okami /app /app

USER okami

# A app carrega .env sozinha (python-dotenv); workspaces vêm por volume. $OKAMI_HOME (skills,
# agents, sessões, .env, credenciais) vive em /data — monte um volume nele (ver docker-compose.yml)
# ou o estado se perde a cada `docker compose down` / recriação do container.
VOLUME ["/data"]

# `okami --version` é rápido, não bate rede/provider — falha só se o venv/entrypoint quebrou.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["okami", "--version"]

ENTRYPOINT ["okami"]
CMD ["doctor"]
