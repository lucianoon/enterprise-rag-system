# Docker deployment

`docker compose up --build` starts two services:

- **api** — the FastAPI app, configured via environment to use the real
  backends: `RAG_VECTOR_STORE=qdrant` and `RAG_EMBEDDING_BACKEND=tfidf`.
- **qdrant** — a Qdrant instance with a persistent volume
  (`qdrant_storage`). On startup, the API builds a new immutable collection
  named `enterprise_docs__generation_<uuid>` and pins itself to that generation
  only after completed writes and exact count validation. Existing collections
  are never overwritten or deleted by indexing.

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

For a custom corpus, mount a readable JSONL file or directory into the API
container as read-only and set `RAG_DOCUMENTS_PATH` to its container path.
Each record needs a unique `doc_id`, nonblank `title` and nonblank `text`.
An explicitly invalid corpus fails startup instead of falling back to samples.

Each restart creates another generation; old and failed generations are retained.
This prevents destructive replacement but requires storage monitoring and manual
retention management. Do not delete a generation still used by a running process.
The JSONL source needs its own backup; vector payloads do not contain full text.
See [the deployment limits and next lifecycle steps](../docs/SAFE_INGESTION_STRATEGY.md).
