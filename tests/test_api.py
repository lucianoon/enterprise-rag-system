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


def test_api_stays_open_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post("/query", json={"question": "refund policy", "top_k": 1})
    assert response.status_code == 200

