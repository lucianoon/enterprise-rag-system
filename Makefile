.PHONY: install test lint typecheck check eval dev docker-up docker-down

install:
	uv sync --extra dev --extra extras

test:
	uv run pytest -q

lint:
	uv run ruff check .

typecheck:
	uv run mypy

# Os mesmos gates que o CI aplica.
check: lint typecheck test

eval:
	uv run python -m enterprise_rag_system.evaluation

dev:
	uv run uvicorn enterprise_rag_system.api:app --reload --host 0.0.0.0 --port 8000

docker-up:
	docker compose up --build

docker-down:
	docker compose down --volumes
