FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# Camada de dependências: só invalida quando o lockfile muda.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --extra extras --locked --no-install-project --no-dev

COPY . .
RUN uv sync --extra extras --locked --no-dev

EXPOSE 8000

# PaaS como o Render injetam PORT; localmente o default continua 8000.
CMD ["sh", "-c", "uvicorn enterprise_rag_system.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
