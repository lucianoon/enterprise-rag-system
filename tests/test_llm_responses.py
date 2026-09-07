"""Exercise completion handling with SDK responses, without external calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system import llm_client
from enterprise_rag_system.generation import LLMAnswerGenerator
from enterprise_rag_system.models import Chunk
from enterprise_rag_system.pipeline import RAGPipeline


@pytest.fixture
def openai_client(monkeypatch):
    openai = pytest.importorskip("openai")
    client = Mock()
    monkeypatch.setattr(openai, "OpenAI", Mock(return_value=client))
    monkeypatch.setenv("RAG_LLM_BACKEND", "openai")
    monkeypatch.setenv("RAG_LLM_API_KEY", "test-key")
    return client


def _completion(content, refusal=None, finish_reason="stop"):
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate({
        "id": "test-completion",
        "created": 0,
        "model": "test-model",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content, "refusal": refusal},
        }],
    })


def test_openai_text_is_returned_and_request_parameters_are_preserved(openai_client):
    openai_client.chat.completions.create.return_value = _completion("  Supported answer [1].  ")

    answer = llm_client.complete("system", "question", model="test-model", max_tokens=123)

    assert answer == "Supported answer [1]."
    openai_client.chat.completions.create.assert_called_once_with(
        model="test-model",
        max_tokens=123,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ],
    )


@pytest.mark.parametrize("content", [None, "", " \n\t "])
def test_openai_empty_text_is_not_a_success(openai_client, content):
    openai_client.chat.completions.create.return_value = _completion(content)

    with pytest.raises(RuntimeError, match="no text"):
        llm_client.complete("system", "question")


@pytest.mark.parametrize("content", [None, "Partial response"])
def test_openai_refusal_is_not_a_success(openai_client, content):
    openai_client.chat.completions.create.return_value = _completion(content, refusal="Declined")

    with pytest.raises(RuntimeError, match="refused"):
        llm_client.complete("system", "question")


def test_openai_filtered_completion_is_not_a_success(openai_client):
    openai_client.chat.completions.create.return_value = _completion(
        "Partial response", finish_reason="content_filter"
    )

    with pytest.raises(RuntimeError, match="filtered"):
        llm_client.complete("system", "question")


def test_openai_missing_choices_has_explicit_error(openai_client):
    completion = _completion("unused")
    completion.choices = []
    openai_client.chat.completions.create.return_value = completion

    with pytest.raises(RuntimeError, match="no completion choices"):
        llm_client.complete("system", "question")


@pytest.mark.parametrize("content,refusal", [(None, None), (None, "Declined")])
def test_query_returns_visible_fallback_for_unusable_openai_response(
    monkeypatch, openai_client, content, refusal
):
    from enterprise_rag_system import api

    openai_client.chat.completions.create.return_value = _completion(content, refusal=refusal)
    pipeline = RAGPipeline(
        [Chunk(chunk_id="refund:0", doc_id="refund", title="Refund", text="Refunds take 30 days.")],
        answer_generator=LLMAnswerGenerator(),
    )
    monkeypatch.setattr(api, "pipeline", pipeline)
    monkeypatch.delenv("RAG_API_KEY", raising=False)

    response = TestClient(api.app).post("/query", json={"question": "Refund timeframe?"})

    assert response.status_code == 200
    body = response.json()
    assert "30 days" in body["answer"]
    assert body["metadata"]["generation_mode"] == "deterministic-fallback"


@pytest.fixture
def anthropic_client(monkeypatch):
    import anthropic

    client = Mock()
    monkeypatch.setattr(anthropic, "Anthropic", Mock(return_value=client))
    monkeypatch.setenv("RAG_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("RAG_LLM_API_KEY", "test-key")
    return client


@pytest.mark.parametrize("content", [[], [SimpleNamespace(type="text", text="  \n ")]])
def test_anthropic_empty_text_is_not_a_success(anthropic_client, content):
    anthropic_client.messages.create.return_value = SimpleNamespace(
        content=content, stop_reason="end_turn"
    )

    with pytest.raises(RuntimeError, match="no text"):
        llm_client.complete("system", "question")


def test_anthropic_refusal_is_not_a_success(anthropic_client):
    anthropic_client.messages.create.return_value = SimpleNamespace(
        content=[], stop_reason="refusal"
    )

    with pytest.raises(RuntimeError, match="refused"):
        llm_client.complete("system", "question")


def test_anthropic_text_blocks_are_combined(anthropic_client):
    anthropic_client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking"),
            SimpleNamespace(type="text", text=" Supported"),
            SimpleNamespace(type="text", text=" answer [1]. "),
        ],
    )

    assert llm_client.complete("system", "question") == "Supported answer [1]."
