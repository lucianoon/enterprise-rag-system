"""API tests."""

from fastapi.testclient import TestClient

from enterprise_rag_system.api import app


def test_health():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_endpoint():
    client = TestClient(app)
    response = client.post(
        "/query",
        json={"question": "What does the security policy say about CPF?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert body["citations"][0]["doc_id"] == "policy_security"


def test_query_rejects_invalid_payload():
    client = TestClient(app)

    assert client.post("/query", json={"question": ""}).status_code == 422
    assert client.post("/query", json={"question": "ok", "top_k": 99}).status_code == 422


def test_evaluate_batch_endpoint_reports_aggregate_metrics():
    client = TestClient(app)
    response = client.post("/evaluate/batch", json={"top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "retrieval_v1"
    assert body["example_count"] == 10
    assert len(body["per_query"]) == 10
    assert 0.0 <= body["mean_recall_at_k"] <= 1.0
    assert 0.0 <= body["mean_mrr"] <= 1.0


def test_api_key_protects_query_endpoints(monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "test-secret")
    client = TestClient(app)
    payload = {"question": "What is the refund policy?", "top_k": 3}

    assert client.post("/query", json=payload).status_code == 401
    assert client.post("/evaluate/batch", json={"top_k": 3}).status_code == 401
    assert client.get("/health").status_code == 200

    authed = client.post("/query", json=payload, headers={"X-API-Key": "test-secret"})
    assert authed.status_code == 200


def test_evaluate_answer_endpoint_judges_generated_answer(monkeypatch):
    monkeypatch.setenv("RAG_JUDGE_MODE", "heuristic")
    client = TestClient(app)
    response = client.post(
        "/evaluate/answer",
        json={"question": "What is the SLA for high priority tickets?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["judgement"]["judge_mode"] == "heuristic"
    assert 0.0 <= body["judgement"]["faithfulness"] <= 1.0
    assert body["query"]["answer"]


def test_api_stays_open_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post("/query", json={"question": "refund policy", "top_k": 1})
    assert response.status_code == 200



def test_bm25_configuration_is_used_by_http_query(monkeypatch):
    from enterprise_rag_system import api

    monkeypatch.setenv('RAG_RETRIEVAL_MODE', 'bm25')
    monkeypatch.setattr(api, 'pipeline', api.build_pipeline())
    response = TestClient(app).post('/query', json={'question': 'refund', 'top_k': 2})
    assert response.status_code == 200
    assert response.json()['metadata']['retrieval_mode'] == 'bm25'
    assert response.json()['citations'][0]['doc_id'] == 'policy_refunds'


def test_invalid_retrieval_configuration_fails_at_build(monkeypatch):
    import pytest

    from enterprise_rag_system.api import build_pipeline

    monkeypatch.setenv('RAG_RETRIEVAL_MODE', 'typo')
    with pytest.raises(ValueError, match='RAG_RETRIEVAL_MODE'):
        build_pipeline()


def test_custom_document_corpus_is_used_by_query(tmp_path, monkeypatch):
    import json

    from enterprise_rag_system import api

    source = tmp_path / 'company.jsonl'
    source.write_text(json.dumps({
        'doc_id': 'company_refunds', 'title': 'Reembolso de viagem',
        'text': 'Reembolsos devem ser solicitados pelo portal da empresa.',
    }))
    monkeypatch.setenv('RAG_DOCUMENTS_PATH', str(source))
    monkeypatch.setenv('RAG_RETRIEVAL_MODE', 'bm25')
    monkeypatch.setattr(api, 'pipeline', api.build_pipeline())
    result = TestClient(app).post('/query', json={'question': 'reembolso viagem'})
    assert result.status_code == 200
    assert {c['doc_id'] for c in result.json()['citations']} == {'company_refunds'}


def test_invalid_configured_corpus_never_falls_back_or_initializes_backends(tmp_path, monkeypatch):
    import pytest

    from enterprise_rag_system import api

    def forbidden(*args, **kwargs):
        pytest.fail('Invalid corpus must be rejected before backend initialization')

    monkeypatch.setattr(api, 'RAGPipeline', forbidden)
    for value in ['', str(tmp_path / 'missing.jsonl')]:
        monkeypatch.setenv('RAG_DOCUMENTS_PATH', value)
        with pytest.raises((ValueError, FileNotFoundError)):
            api.build_pipeline()
    invalid = tmp_path / 'invalid.jsonl'
    invalid.write_text('')
    monkeypatch.setenv('RAG_DOCUMENTS_PATH', str(invalid))
    with pytest.raises(ValueError, match='Corpus'):
        api.build_pipeline()
