# Atalhos de dev (Linux/macOS). No Windows, use o venv direto (ver README).
.PHONY: install install-global setup test run doctor lint docker-build docker-test docker-run

install:               ## dev: venv + deps via uv (a partir do pyproject)
	uv sync

install-global:        ## instala o comando `okami` global e isolado (igual ao curl | bash)
	./scripts/install.sh

setup:                 ## wizard de configuração (provider/memória/identidade/canal)
	okami setup

test:
	uv run pytest -q

doctor:
	okami doctor

docker-build:
	docker build -f deploy/Dockerfile -t okami-agent .

docker-test:
	docker run --rm --entrypoint python okami-agent -m pytest -q

docker-run:
	docker compose -f deploy/docker-compose.yml run --rm okami doctor
