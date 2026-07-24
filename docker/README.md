# Docker deployment

`docker compose up --build` starts two services:

- **api** — the FastAPI app, configured via environment to use the real
  backends: `RAG_VECTOR_STORE=qdrant` and `RAG_EMBEDDING_BACKEND=tfidf`.
- **qdrant** — a Qdrant instance with a persistent volume
  (`qdrant_storage`). The api service indexes the sample corpus into the
  `enterprise_docs` collection on startup.

Environment overrides go in a `.env` file at the repo root (optional — see
`.env.example`). To require authentication, set `RAG_API_KEY` and send the
same value in the `X-API-Key` header on `/query` and `/evaluate*` requests.

Smoke test once it is up:

```bash
curl -s localhost:8000/health
curl -s -X POST localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How fast is first response for high priority tickets?"}'
curl -s -X POST localhost:8000/evaluate/batch \
  -H "Content-Type: application/json" -d '{"top_k": 3}'
```
