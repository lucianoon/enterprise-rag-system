import pytest

from enterprise_rag_system.models import Chunk
from enterprise_rag_system.product_reranker import rerank


@pytest.mark.parametrize(
    "response,expected,mode",
    [
        ('["b:0","a:0"]', "b", "llm"),
        ('["foreign:0","a:0"]', "a", "rrf-fallback"),
        ('["a:0","a:0"]', "a", "rrf-fallback"),
        ("not json", "a", "rrf-fallback"),
        ('["b:0"]', "b", "llm"),
        ("[]", "a", "rrf-fallback"),
    ],
)
def test_only_unique_authorized_rankings_are_accepted(monkeypatch, response, expected, mode):
    monkeypatch.setattr(
        "enterprise_rag_system.product_reranker.llm_client.complete",
        lambda *args, **kwargs: response,
    )
    chunks = [Chunk(doc_id=key, chunk_id=key + ":0", title=key, text=key) for key in ["a", "b"]]
    selected, status = rerank("question", chunks, 1)
    assert selected[0].doc_id == expected
    assert status == mode
