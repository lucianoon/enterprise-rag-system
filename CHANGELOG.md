# Changelog

## Unreleased

- Added Claude-backed answer generation (`generation.py`) with a pluggable
  `AnswerGenerator` interface and a deterministic fallback for CI.
- Added `RAG_LLM_MODE` / `RAG_LLM_MODEL` configuration and `generation_mode`
  query metadata.
- Replaced the `OPENAI_API_KEY` placeholder with `ANTHROPIC_API_KEY` in
  `.env.example`.

## 0.1.0

- Initial hybrid RAG scaffold.
- Added deterministic lexical and vector retrieval.
- Added reranking and citation-aware answer composition.
- Added FastAPI query and evaluation endpoints.
- Added sample enterprise documents.

