PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

export PYTHONPATH := src

.PHONY: install test dev docker-up docker-down

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test:
	$(PY) -m pytest -q

dev:
	$(VENV)/bin/uvicorn enterprise_rag_system.api:app --reload --host 0.0.0.0 --port 8000

docker-up:
	docker compose up --build

docker-down:
	docker compose down --volumes

