# Changelog

## Unreleased

- Reproducible builds: `pyproject.toml` + `uv.lock` replace `requirements.txt`
  and `requirements-extras.txt`, so local, CI and the Docker image resolve the
  exact same versions. Optional backends moved to the `extras` group.
- CI gates on `ruff` and `mypy` in addition to `pytest`, and builds the Docker
  image so the deploy path is covered too.
- Fixes surfaced by the new gates: `zip()` calls made length-strict in the
  vector stores, `Counter` annotated in the lexical index, module-level imports
  moved to the top of `generation.py` and `answer_eval.py`, and typing
  modernized to PEP 585/604.

## 0.3.0

- Answer faithfulness evaluation (`answer_eval.py`): judges whether the
  generated answer is grounded in its retrieved passages.
- Two judges behind one interface, selected by `RAG_JUDGE_MODE`: a
  deterministic per-sentence lexical containment heuristic (default, CI-safe)
  and Claude as an LLM judge (`RAG_JUDGE_MODEL`), with logged fallback to the
  heuristic on API errors.
- `POST /evaluate/answer` endpoint returning faithfulness, unsupported claims
  and the full query response.

## 0.2.0

- Pluggable embedding backends (`embeddings.py`): deterministic hashing
  (default), TF-IDF via scikit-learn, and sentence-transformers — selected by
  `RAG_EMBEDDING_BACKEND`.
- Fixed non-deterministic embeddings: token bucketing now uses `hashlib.md5`
  instead of Python's per-process randomized `hash()`.
- Pluggable vector stores (`vector_store.py`): in-memory (default) and a real
  Qdrant integration (`RAG_VECTOR_STORE=qdrant`) — `QDRANT_URL` and
  `COLLECTION_NAME` are now actually used, and `docker-compose.yml` wires the
  API to the Qdrant service it always started.
- Batch retrieval evaluation: versioned dataset
  (`data/eval/retrieval_v1.jsonl`), `/evaluate/batch` endpoint,
  `python -m enterprise_rag_system.evaluation` CLI and `make eval`.
- Optional API-key auth (`RAG_API_KEY` + `X-API-Key` header) on all endpoints
  except `/health`.
- Structured logging with `LOG_LEVEL`; the Claude fallback path now logs the
  underlying exception instead of swallowing it.
- Dockerfile aligned to Python 3.12 (matching CI and README); optional
  dependencies split into `requirements-extras.txt`; CI installs extras and
  runs the full 29-test suite.

- Claude-backed answer generation (`generation.py`) with a pluggable
  `AnswerGenerator` interface and a deterministic fallback for CI.
- `RAG_LLM_MODE` / `RAG_LLM_MODEL` configuration and `generation_mode`
  query metadata.
- Replaced the `OPENAI_API_KEY` placeholder with `ANTHROPIC_API_KEY` in
  `.env.example`.

## 0.1.0

- Initial hybrid RAG scaffold.
- Added deterministic lexical and vector retrieval.
- Added reranking and citation-aware answer composition.
- Added FastAPI query and evaluation endpoints.
- Added sample enterprise documents.

