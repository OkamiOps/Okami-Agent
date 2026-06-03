# Okami Agent — imagem Linux (também resolve o long-path do Windows ao desenvolver em container).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Deps primeiro (cache de camada).
COPY pyproject.toml README.md ./
COPY okami ./okami
COPY tests ./tests
COPY okami.yaml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# A app carrega .env sozinha (python-dotenv); workspaces vêm por volume.
ENTRYPOINT ["okami"]
CMD ["doctor"]
