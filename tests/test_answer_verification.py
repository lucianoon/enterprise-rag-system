import json

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.answer_verification import Review, review
from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_store import DocumentInput


@pytest.mark.parametrize(
    "claims",
    [
        [],
        [{"statement": "RAG busca documentos", "source": 1, "quote": "invented quote"}],
        [{"statement": "invented statement", "source": 1, "quote": "RAG busca documentos"}],
        [{"statement": "RAG busca documentos", "source": 2, "quote": "RAG busca documentos"}],
    ],
)
def test_review_rejects_fabricated_or_missing_evidence(monkeypatch, claims):
    monkeypatch.setattr(
        "enterprise_rag_system.answer_verification.llm_client.complete",
        lambda *a, **k: json.dumps({"verdict": "supported", "issues": [], "claims": claims}),
    )
    with pytest.raises(ValueError):
        review(
            "RAG?", "RAG busca documentos [1].", [{"number": 1, "excerpt": "RAG busca documentos"}]
        )


def test_insufficient_and_unavailable_do_not_become_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_PRODUCT_VERIFY", "true")
    app = create_product_app(tmp_path / "db", generation="llm")
    token = app.state.registry.issue_user("a", "owner", "admin")
    app.state.registry.write_document(
        token, "rag", DocumentInput(title="RAG", text="RAG busca documentos.", expected_revision=0)
    )
    monkeypatch.setattr(
        "enterprise_rag_system.product_api.llm_client.complete",
        lambda *a, **k: "RAG garante sempre a verdade [1].",
    )
    monkeypatch.setattr(
        "enterprise_rag_system.product_api.review",
        lambda *a: Review(verdict="insufficient", issues=["Sem evidência"], claims=[]),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + token}
    result = client.post(
        "/query", headers=headers, json={"question": "RAG garante verdade?"}
    ).json()
    assert result["abstained"] and result["citations"] == []
    assert result["metadata"]["verification"] == "insufficient"

    def offline(*a):
        raise RuntimeError("offline")

    monkeypatch.setattr("enterprise_rag_system.product_api.review", offline)
    result = client.post("/query", headers=headers, json={"question": "RAG?"}).json()
    assert result["abstained"]
    assert result["metadata"]["verification"] == "unavailable"


def test_revision_must_pass_a_second_review(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_PRODUCT_VERIFY", "true")
    app = create_product_app(tmp_path / "db", generation="llm")
    token = app.state.registry.issue_user("a", "owner", "admin")
    app.state.registry.write_document(
        token, "rag", DocumentInput(title="RAG", text="RAG busca documentos.", expected_revision=0)
    )
    answers = iter(["RAG garante a verdade [1].", "RAG busca documentos [1]."])
    monkeypatch.setattr(
        "enterprise_rag_system.product_api.llm_client.complete", lambda *a, **k: next(answers)
    )
    reviews = iter(
        [
            Review(verdict="revise", issues=["Excesso de certeza"], claims=[]),
            Review(verdict="supported", issues=[], claims=[]),
        ]
    )
    monkeypatch.setattr("enterprise_rag_system.product_api.review", lambda *a: next(reviews))
    result = (
        TestClient(app)
        .post("/query", headers={"Authorization": "Bearer " + token}, json={"question": "RAG?"})
        .json()
    )
    assert not result["abstained"]
    assert result["answer"] == "RAG busca documentos [1]."
    assert result["metadata"]["verification"] == "supported"


def test_review_retries_invalid_quote_and_accepts_original_language(monkeypatch):
    reports = iter(
        [
            {
                "verdict": "supported",
                "issues": [],
                "claims": [
                    {
                        "statement": "RAG busca documentos",
                        "source": 1,
                        "quote": "RAG busca documentos",
                    }
                ],
            },
            {
                "verdict": "supported",
                "issues": [],
                "claims": [
                    {
                        "statement": "RAG busca documentos",
                        "source": 1,
                        "quote": "RAG retrieves documents",
                    }
                ],
            },
        ]
    )
    calls = []

    def complete(system, *args, **kwargs):
        calls.append(system)
        return json.dumps(next(reports))

    monkeypatch.setattr("enterprise_rag_system.answer_verification.llm_client.complete", complete)
    result = review(
        "RAG?",
        "RAG busca documentos [1].",
        [{"number": 1, "excerpt": "RAG retrieves documents for generation."}],
    )
    assert result.verdict == "supported"
    assert len(calls) == 2
    assert "prior report failed validation" in calls[1]


def test_review_rejects_evidence_cited_in_another_paragraph(monkeypatch):
    monkeypatch.setattr(
        "enterprise_rag_system.answer_verification.llm_client.complete",
        lambda *a, **k: json.dumps(
            {
                "verdict": "supported",
                "issues": [],
                "claims": [
                    {"statement": "Retrieval", "source": 2, "quote": "Retrieval"},
                    {"statement": "Generation", "source": 2, "quote": "Generation"},
                ],
            }
        ),
    )
    with pytest.raises(ValueError, match="cited source"):
        review(
            "RAG?",
            "Retrieval [1].\n\nGeneration [2].",
            [
                {"number": 1, "excerpt": "Retrieval"},
                {"number": 2, "excerpt": "Retrieval and Generation"},
            ],
        )
