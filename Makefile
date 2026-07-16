.PHONY: setup install test lint format clean docker-up docker-down

install:
	cd backend && pip install -r requirements.txt
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

test:
	pytest backend

test-cov:
	pytest backend --cov=backend/api --cov=backend/agents --cov=backend/rag --cov=backend/utils --cov-report=term-missing && pytest

lint:
	cd backend && ruff check .

format:
	cd backend && ruff format .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
