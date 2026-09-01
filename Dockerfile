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

# Processo sem root: a API só lê o próprio código e o corpus de exemplo.
RUN useradd --system --uid 1000 --no-create-home rag && chown -R rag:rag /app
USER rag

EXPOSE 8000

# Consulta o /health da própria API (sempre aberto, mesmo com RAG_API_KEY). A
# imagem slim não tem curl, então o probe usa a stdlib e respeita PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c 'import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen("http://localhost:%s/health" % os.environ.get("PORT","8000"), timeout=4).status==200 else 1)'

# PaaS como o Render injetam PORT; localmente o default continua 8000.
CMD ["sh", "-c", "uvicorn enterprise_rag_system.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
