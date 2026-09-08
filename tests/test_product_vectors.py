"""Persistent semantic retrieval, cache invalidation, ACL and failure contracts."""

from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_store import DocumentInput, Registry
from enterprise_rag_system.product_vectors import ProductVectors


def fake(texts):
    # A deterministic semantic fixture: no lexical overlap needed.
    return [[1.0, *([0.0] * 1535)] for _ in texts]


def test_persistence_content_changes_and_tenant_isolation(tmp_path):
    store = Registry(tmp_path / "db")
    token = store.issue_user("a", "user", "admin")
    calls = []

    def embed(texts):
        calls.extend(texts)
        return fake(texts)

    store.write_document(
        token, "one", DocumentInput(title="Test", text="hello", expected_revision=0)
    )
    vectors = ProductVectors(store, embed)
    assert vectors.sync(token)["chunks"] == 1
    ProductVectors(store, embed).sync(token)
    assert len(calls) == 1
    store.write_document(
        token, "one", DocumentInput(title="Test", text="changed", expected_revision=1)
    )
    vectors.sync(token)
    assert len(calls) == 2
    other = store.issue_user("b", "user", "admin")
    store.write_document(
        other, "one", DocumentInput(title="Test", text="changed", expected_revision=0)
    )
    vectors.sync(other)
    assert len(calls) == 3


def test_save_hybrid_acl_delete_and_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_PRODUCT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(ProductVectors, "_openai", lambda self, texts: fake(texts))
    app = create_product_app(tmp_path / "db")
    store = app.state.registry
    admin = store.issue_user("a", "owner", "admin")
    reader = store.issue_user("a", "reader", "reader")
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + admin}
    payload = {
        "title": "Transport",
        "text": "The automobile needs maintenance.",
        "expected_revision": 0,
    }
    assert client.put("/documents/one", json=payload, headers=headers).json()["indexing"] == "ready"
    result = client.post("/query", json={"question": "car repair"}, headers=headers).json()
    assert result["metadata"]["retrieval_mode"] == "hybrid"
    assert result["citations"][0]["doc_id"] == "one"
    hidden = client.post(
        "/query", json={"question": "car repair"}, headers={"Authorization": "Bearer " + reader}
    ).json()
    assert hidden["abstained"]
    assert (
        client.post("/index/sync", headers={"Authorization": "Bearer " + reader}).status_code == 403
    )

    def unavailable(texts):
        raise RuntimeError("offline")

    app.state.vectors.embed = unavailable
    failed = client.post("/query", json={"question": "automobile"}, headers=headers).json()
    assert failed["metadata"]["retrieval_mode"] == "bm25-semantic-fallback"
    payload.update(text="Updated maintenance instructions.", expected_revision=1)
    assert (
        client.put("/documents/one", json=payload, headers=headers).json()["indexing"] == "pending"
    )
    assert client.get("/documents/one", headers=headers).json()["revision"] == 2
    assert client.delete("/documents/one?expected_revision=2", headers=headers).status_code == 200
    empty = client.post("/query", json={"question": "automobile"}, headers=headers).json()
    assert empty["abstained"]


def test_index_file_then_ask_only_that_document(tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("RAG_PRODUCT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(ProductVectors, "_openai", lambda self, texts: fake(texts))
    monkeypatch.setattr(
        "enterprise_rag_system.product_api.extract",
        lambda data, name: {"text": data.decode(), "ocr_pages": []},
    )
    app = create_product_app(tmp_path / "db")
    client = TestClient(app)
    admin = app.state.registry.issue_user("a", "owner", "admin")
    reader = app.state.registry.issue_user("a", "reader", "reader")
    headers = {"Authorization": "Bearer " + admin}
    data = {
        "filename": "Manual.txt",
        "content": base64.b64encode(b"The code is BLUE.").decode(),
        "doc_id": "manual",
    }
    response = client.post("/imports/index", json=data, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["indexing"] == "ready"
    saved = client.get("/documents/manual", headers=headers).json()
    assert saved["text"] == "The code is BLUE."
    assert saved["visibility"] == "private"
    client.put(
        "/documents/other",
        headers=headers,
        json={"title": "Other", "text": "The code is RED.", "expected_revision": 0},
    )
    question = {"question": "What is the code?", "doc_id": "manual"}
    answer = client.post("/query", headers=headers, json=question).json()
    assert {c["doc_id"] for c in answer["citations"]} == {"manual"}
    assert (
        client.post(
            "/query", json=question, headers={"Authorization": "Bearer " + reader}
        ).status_code
        == 404
    )
    assert client.post("/imports/index", json=data, headers=headers).status_code == 409
    assert client.get("/documents/manual", headers=headers).json()["revision"] == 1

    def offline(texts):
        raise RuntimeError("offline")

    app.state.vectors.embed = offline
    data.update(doc_id="failed", content=base64.b64encode(b"New material").decode())
    assert client.post("/imports/index", json=data, headers=headers).status_code == 503
    assert client.get("/documents/failed", headers=headers).status_code == 404
