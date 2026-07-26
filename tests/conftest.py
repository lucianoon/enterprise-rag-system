"""Shared test setup.

The suite is meant to run fully offline. Without this, a developer with
``ANTHROPIC_API_KEY`` exported gets a different suite than CI does: the
generator and judge resolve to their live backends and the tests make real,
billable API calls — two of them then fail on the non-deterministic output.
Clearing the selection variables for every test makes the run hermetic
regardless of the machine it runs on.
"""

import pytest

_LLM_ENV = (
    "RAG_LLM_MODE",
    "RAG_LLM_BACKEND",
    "RAG_LLM_MODEL",
    "RAG_LLM_BASE_URL",
    "RAG_LLM_API_KEY",
    "RAG_JUDGE_MODE",
    "RAG_JUDGE_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


@pytest.fixture(autouse=True)
def offline_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
