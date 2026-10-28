.DEFAULT_GOAL := help
.PHONY: help install dev-backend dev-frontend migrate seed index lint format typecheck \
        test test-backend test-frontend eval check docker-up docker-down clean

BACKEND  := cd backend &&
FRONTEND := cd frontend &&

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (dev) and frontend dependencies, and git hooks
	$(BACKEND) pip install torch --index-url https://download.pytorch.org/whl/cpu
	$(BACKEND) pip install -r requirements-dev.txt
	$(FRONTEND) npm ci
	pre-commit install

dev-backend: ## Run the API with auto-reload on :8000
	$(BACKEND) uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Vite dev server on :5173 (proxies /api to :8000)
	$(FRONTEND) npm run dev

migrate: ## Apply database migrations
	$(BACKEND) alembic upgrade head

seed: ## Load market data, generate the demo portfolio and index the schema
	$(BACKEND) python -m app.cli seed

index: ## Rebuild the schema vector index
	$(BACKEND) python -m app.cli index-schema

lint: ## Lint backend and frontend
	$(BACKEND) ruff check . && ruff format --check .
	$(FRONTEND) npm run lint

format: ## Auto-format the backend
	$(BACKEND) ruff check --fix . && ruff format .

typecheck: ## Static type-check the backend
	$(BACKEND) mypy

test-backend: ## Run backend tests with coverage
	$(BACKEND) pytest --cov

test-frontend: ## Run frontend tests
	$(FRONTEND) npm test

test: test-backend test-frontend ## Run all tests

eval: ## Score the live pipeline on eval/cases.json (needs seeded DB + LLM key)
	$(BACKEND) python -m eval.run

check: lint typecheck test ## Everything CI runs (except Docker builds)

docker-up: ## Build and start the full stack
	docker compose up -d --build

docker-down: ## Stop the stack (data volumes are kept)
	docker compose down

clean: ## Remove caches and build output
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf backend/.coverage backend/coverage.xml frontend/dist frontend/coverage
