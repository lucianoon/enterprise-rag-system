"""Backend resolution for the single LLM port — no network."""

import pytest

from enterprise_rag_system import llm_client


class TestResolveBackend:
    def test_none_when_unconfigured(self):
        assert llm_client.resolve_backend() is None

    def test_anthropic_key_wins_in_auto(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert llm_client.resolve_backend() == "anthropic"

    def test_openai_when_only_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert llm_client.resolve_backend() == "openai"

    def test_base_url_alone_selects_openai(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BASE_URL", "http://localhost:11434/v1")
        assert llm_client.resolve_backend() == "openai"

    def test_explicit_backend_overrides_auto(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.setenv("RAG_LLM_BACKEND", "openai")
        assert llm_client.resolve_backend() == "openai"

    def test_invalid_backend_raises(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BACKEND", "gemini")
        with pytest.raises(ValueError, match="Invalid RAG_LLM_BACKEND"):
            llm_client.resolve_backend()


class TestResolve:
    def test_raises_when_unconfigured(self):
        with pytest.raises(RuntimeError, match="No model configured"):
            llm_client.resolve()

    def test_anthropic_defaults(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        config = llm_client.resolve()
        assert config.backend == "anthropic"
        assert config.model == llm_client.DEFAULT_ANTHROPIC_MODEL
        assert config.base_url is None

    def test_openai_defaults(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        config = llm_client.resolve()
        assert config.backend == "openai"
        assert config.model == llm_client.DEFAULT_OPENAI_MODEL

    def test_env_model_overrides_default(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.setenv("RAG_LLM_MODEL", "claude-sonnet-5")
        assert llm_client.resolve().model == "claude-sonnet-5"

    def test_argument_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.setenv("RAG_LLM_MODEL", "claude-sonnet-5")
        assert llm_client.resolve("claude-opus-5").model == "claude-opus-5"

    def test_local_server_gets_placeholder_key(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BASE_URL", "http://localhost:11434/v1")
        config = llm_client.resolve()
        assert config.api_key == llm_client.LOCAL_PLACEHOLDER_KEY
        assert config.base_url == "http://localhost:11434/v1"

    def test_explicit_key_beats_placeholder(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BASE_URL", "https://openrouter.ai/api/v1")
        monkeypatch.setenv("RAG_LLM_API_KEY", "sk-or-v1-real")
        assert llm_client.resolve().api_key == "sk-or-v1-real"


class TestAvailability:
    def test_unavailable_when_unconfigured(self):
        assert llm_client.is_available() is False

    def test_available_with_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert llm_client.is_available() is True

    def test_invalid_backend_is_not_available(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BACKEND", "gemini")
        assert llm_client.is_available() is False


class TestDescribe:
    def test_unconfigured(self):
        assert llm_client.describe() == "unconfigured"

    def test_names_the_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert llm_client.describe() == llm_client.DEFAULT_ANTHROPIC_MODEL

    def test_includes_base_url(self, monkeypatch):
        monkeypatch.setenv("RAG_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("RAG_LLM_MODEL", "llama3.1")
        assert llm_client.describe() == "llama3.1 @ http://localhost:11434/v1"
