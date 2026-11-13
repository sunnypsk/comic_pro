PWSH ?= powershell

.PHONY: help install dev-backend dev-web build test lint up down logs smoke

help:
	@echo "ComicPro targets:"
	@echo "  install      install backend (uv) and frontend (pnpm) dependencies"
	@echo "  dev-backend  run FastAPI on :8080 with autoreload"
	@echo "  dev-web      run Vite dev server on :5173 (proxies /api to :8080)"
	@echo "  build        type-check + build the frontend bundle"
	@echo "  test         run backend tests"
	@echo "  lint         ruff + tsc"
	@echo "  up / down    docker compose up -d / down"
	@echo "  smoke        docker build + end-to-end container smoke test"

install:
	uv sync --group dev
	pnpm -C frontend install

dev-backend:
	uv run uvicorn app.main:create_app --factory --app-dir backend --reload --port 8080

dev-web:
	pnpm -C frontend dev

build:
	pnpm -C frontend run build

test:
	uv run pytest -q

lint:
	uv run ruff check backend
	pnpm -C frontend run typecheck

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

smoke:
	$(PWSH) -NoProfile -ExecutionPolicy Bypass -File scripts/smoke.ps1
