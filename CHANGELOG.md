# Changelog

## Unreleased

- Replace destructive Qdrant reindexing with immutable physical generations.
  Validate the complete input before creating data, wait for every batch, check
  the exact point count, then pin the store instance to the completed generation.
  Retain old and failed generations; do not delete existing collections.
- Validate vector dimensions, finite values and unique IDs for both stores;
  failed replacements preserve the previous view. Empty replacement clears only
  the instance view, leaving retained Qdrant generations untouched.
- Load an operator-specified JSONL corpus through `RAG_DOCUMENTS_PATH`. Reject
  empty/duplicate/blank corpus records before initializing retrieval backends.
- Exercise generation isolation and read-during-build behavior against a
  disposable Qdrant server in CI, as well as the local backend.

- Add opt-in BM25 retrieval with Unicode accent folding, term-frequency
  saturation, document-length normalization and cached posting lists. Add
  reciprocal rank fusion (RRF) as an experimental alternative.
- Select the API retrieval profile with `RAG_RETRIEVAL_MODE`; expose the
  selected profile in response metadata. Preserve the default hybrid ranking.
  BM25/RRF skip the legacy title reranker by default and omit zero-score padding.
- Extend the benchmark with explicit `--strategies` selection, preserving
  the original frozen matrix. Record both improvements and RRF regressions.

- Add a retrieval-only benchmark matrix (lexical, vector, hybrid, hybrid with
  reranking), with Recall, precision, MRR, binary nDCG, median/p95 latency and
  per-query rankings. A synthetic Portuguese corpus contains 30 documents and
  80 queries across dev/test splits, including unanswerable and multi-source cases.
- Freeze the initial hashing test baseline and gate retrieval regressions in CI;
  retain machine-readable reports for 14 days. Validate data hashes, labels and
  comparison settings so changed datasets cannot silently pass as improvements.
- Expose `RAGPipeline.retrieve()` for evaluation without answer generation.
  Default query ranking and the original demo corpus remain the same.

- Repair the duplicate `truststore` package entry that prevented `uv sync --locked`
  and CI from installing dependencies; retain all locked package versions.
- Resolve OpenAI-compatible URLs before ambient provider credentials in `auto`
  mode, so the documented OpenRouter URL + generic key configuration reaches
  the correct endpoint. Explicit `RAG_LLM_BACKEND` still wins; set it to
  `anthropic` to retain that provider when a base URL is also configured.
- Reject empty, refused and filtered LLM responses instead of returning a
  successful empty answer. Both providers reject empty text; the existing
  deterministic fallback remains available and is covered through the HTTP API.
- Report the effective generation mode per request, including
  `deterministic-fallback`, in response metadata and query logs. Preserve the
  text-only `compose` interface and existing custom generators. Add regressions
  for provider selection, response validation and concurrent generation.

- Docker image runs as an unprivileged user and declares a `HEALTHCHECK` against
  `/health`; CI now starts the built image and probes it instead of only
  building it. Dependabot watches `uv` dependencies (monthly, minor/patch
  grouped) in addition to GitHub Actions. `setup-uv` and `upload-artifact`
  bumped to v7.

- Measure branch coverage in CI, retain the machine-readable JSON artifact for 14 days, and enforce an evidence-based 80% minimum after observing an 81% baseline.

- Publish the measured public retrieval baseline (Recall@1 and MRR) with environment, commands, provenance, and explicit limitations of the three-document demo corpus.

- Add a reproducible benchmark protocol, contribution guide, structured issue forms, and a pull request checklist that requires CI gates and retrieval-regression evidence.

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

