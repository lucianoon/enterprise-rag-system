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

