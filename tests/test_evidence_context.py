from fastapi.testclient import TestClient

from enterprise_rag_system.evidence_context import expand_context
from enterprise_rag_system.ingestion import chunk_documents
from enterprise_rag_system.models import Document
from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_store import DocumentInput


def test_windows_complete_cut_passages_without_crossing_documents():
    chunks = chunk_documents(
        [
            Document(doc_id="a", title="A", text=" ".join(str(i) for i in range(320))),
            Document(doc_id="b", title="B", text="PRIVATE"),
        ]
    )
    expanded, members = expand_context([chunks[1], chunks[2]], chunks)
    assert len(expanded) == 1
    assert expanded[0].text.split() == [str(i) for i in range(240)]
    assert members["a:1"] == ["a:0", "a:1", "a:2"]
    assert "PRIVATE" not in expanded[0].text


def test_evidence_requires_current_revision_and_current_access(tmp_path):
    app = create_product_app(tmp_path / "db")
    store = app.state.registry
    owner = store.issue_user("a", "owner", "admin")
    other = store.issue_user("b", "owner", "admin")
    store.write_document(
        owner,
        "doc",
        DocumentInput(
            title="Manual", text=" ".join(str(i) for i in range(240)), expected_revision=0
        ),
    )
    client = TestClient(app)

    def get(token, revision=1, index=1):
        return client.get(
            f"/documents/doc/evidence?revision={revision}&chunk_index={index}",
            headers={"Authorization": "Bearer " + token},
        )

    assert get(other).status_code == 404
    response = get(owner).json()
    assert len(response["chunks"]) == 3
    assert [c["selected"] for c in response["chunks"]] == [False, True, False]
    assert get(owner, index=99).status_code == 404
    assert get(owner, index=-1).status_code == 422
    store.write_document(
        owner, "doc", DocumentInput(title="New", text="Updated", expected_revision=1)
    )
    assert get(owner).status_code == 409
    assert get(owner, revision=2, index=0).json()["chunks"][0]["text"] == "Updated"
    store.revoke("a", "owner")
    assert get(owner, revision=2, index=0).status_code == 401


def test_expanded_text_reaches_model_and_citation(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_PRODUCT_VERIFY", raising=False)
    app = create_product_app(tmp_path / "db", generation="llm")
    store = app.state.registry
    token = store.issue_user("a", "u", "admin")
    store.write_document(
        token,
        "d",
        DocumentInput(
            title="Manual",
            text=" ".join(["antecedente"] * 80 + ["encontrar"] * 80 + ["continuação"] * 80),
            expected_revision=0,
        ),
    )

    def complete(system, prompt, **kwargs):
        assert "antecedente" in prompt and "continuação" in prompt
        return "A informação continua no próximo trecho [1]."

    monkeypatch.setattr("enterprise_rag_system.product_api.llm_client.complete", complete)
    r = (
        TestClient(app)
        .post(
            "/query",
            headers={"Authorization": "Bearer " + token},
            json={"question": "encontrar", "top_k": 1},
        )
        .json()
    )
    assert r["metadata"]["generation_mode"] == "llm-structurally-checked"
    assert r["citations"][0]["context_chunk_ids"] == ["d:0", "d:1", "d:2"]
    assert "continuação" in r["citations"][0]["excerpt"]
