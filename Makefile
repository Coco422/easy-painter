SHELL := /bin/bash
COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif docker-compose version >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)
DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: deps backend frontend deploy

deps:
	@test -f .env || { echo "Missing .env. Run: cp .env.example .env"; exit 1; }
	@trap 'status=$$?; $(DEV_COMPOSE) down --remove-orphans >/dev/null 2>&1 || true; exit $$status' EXIT INT TERM; \
	$(DEV_COMPOSE) up --remove-orphans postgres redis minio minio-init worker

backend:
	@test -f .env || { echo "Missing .env. Run: cp .env.example .env"; exit 1; }
	@cd backend && \
	ln -sf ../.env .env && \
	POSTGRES_DB="$$(grep '^POSTGRES_DB=' ../.env | cut -d= -f2-)"; \
	POSTGRES_USER="$$(grep '^POSTGRES_USER=' ../.env | cut -d= -f2-)"; \
	POSTGRES_PASSWORD="$$(grep '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-)"; \
	POSTGRES_PORT="$$(grep '^POSTGRES_PORT=' ../.env | cut -d= -f2-)"; \
	REDIS_PORT="$$(grep '^REDIS_PORT=' ../.env | cut -d= -f2-)"; \
	MINIO_API_PORT="$$(grep '^MINIO_API_PORT=' ../.env | cut -d= -f2-)"; \
	export DATABASE_URL="postgresql+psycopg://$$POSTGRES_USER:$$POSTGRES_PASSWORD@127.0.0.1:$${POSTGRES_PORT:-5432}/$$POSTGRES_DB"; \
	export REDIS_URL="redis://127.0.0.1:$${REDIS_PORT:-6379}/0"; \
	export CELERY_BROKER_URL="redis://127.0.0.1:$${REDIS_PORT:-6379}/1"; \
	export CELERY_RESULT_BACKEND="redis://127.0.0.1:$${REDIS_PORT:-6379}/2"; \
	export MINIO_ENDPOINT="127.0.0.1:$${MINIO_API_PORT:-9000}"; \
	uv sync && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	@cd frontend && npm install && npm run dev

deploy:
	@test -f .env || { echo "Missing .env. Run: cp .env.example .env"; exit 1; }
	$(COMPOSE) build
	$(COMPOSE) up -d --remove-orphans
