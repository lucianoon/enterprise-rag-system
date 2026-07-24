FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt requirements-extras.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-extras.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "enterprise_rag_system.api:app", "--host", "0.0.0.0", "--port", "8000"]
