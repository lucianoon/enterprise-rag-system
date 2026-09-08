"""Profile integration: actual provider arguments, ACL and explicit fallback behavior."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_profiles import load_profile
from enterprise_rag_system.product_store import DocumentInput


def test_profile_reaches_provider_without_leaking_other_tenant(tmp_path, monkeypatch):
    app = create_product_app(tmp_path / "pilot.db", generation="llm", profile="luiz-herminio")
    store = app.state.registry
    token = store.issue_user("local", "reader", "admin")
    other = store.issue_user("other", "reader", "admin")
    store.write_document(
        token,
        "bio",
        DocumentInput(
            title="Pr. Luiz Hermínio",
            text="Luiz Hermínio é pastor evangélico ligado ao MEVAM.",
            expected_revision=0,
        ),
    )
    store.write_document(
        other,
        "private",
        DocumentInput(title="Luiz Hermínio", text="PRIVATE-OTHER-TENANT", expected_revision=0),
    )
    calls = []

    def complete(system, prompt, **kwargs):
        calls.append((system, prompt))
        return "Luiz Hermínio é pastor evangélico, não padre. [1]"

    monkeypatch.setattr("enterprise_rag_system.product_api.llm_client.complete", complete)
    client = TestClient(app)
    response = client.post(
        "/query",
        headers={"Authorization": "Bearer " + token},
        json={"question": "Luiz Hermínio é padre?"},
    )
    response.raise_for_status()
    body = response.json()
    expected, digest = load_profile("luiz-herminio")
    assert calls[0][0] == expected
    assert "PRIVATE-OTHER-TENANT" not in calls[0][1]
    assert body["metadata"]["prompt_sha256"] == digest
    assert body["metadata"]["editorial_profile"] == "luiz-herminio"
    assert body["metadata"]["generation_mode"] == "llm-structurally-checked"
    assert body["citations"][0]["doc_id"] == "bio"
    assert client.get("/profile").json()["generation"] == "llm"
    assert (
        client.post(
            "/query",
            headers={"Authorization": "Bearer " + token},
            json={"question": "Luiz", "profile": "default"},
        ).status_code
        == 422
    )


def test_extractive_profile_does_not_pretend_to_generate(tmp_path, monkeypatch):
    app = create_product_app(tmp_path / "pilot.db", profile="luiz-herminio")
    store = app.state.registry
    token = store.issue_user("local", "admin", "admin")
    store.write_document(
        token,
        "bio",
        DocumentInput(
            title="Pastor", text="Luiz Hermínio é pastor evangélico.", expected_revision=0
        ),
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Extractive mode must not call a provider")

    monkeypatch.setattr("enterprise_rag_system.product_api.llm_client.complete", unexpected)
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + token}
    body = client.post("/query", headers=auth, json={"question": "Luiz Hermínio"}).json()
    assert body["metadata"]["generation_mode"] == "extractive"
    assert client.get("/profile").json()["profile"] == "luiz-herminio"
    empty = client.post("/query", headers=auth, json={"question": "xyzunknown"}).json()
    assert empty["abstained"] is True


@pytest.mark.parametrize("name", ["", "invalid", "../prompts/luiz-herminio"])
def test_invalid_profile_fails_before_creating_database(tmp_path, name):
    path = tmp_path / "not-created.db"
    with pytest.raises(ValueError, match="RAG_PRODUCT_PROFILE"):
        create_product_app(path, profile=name)
    assert not path.exists()


def test_missing_profile_asset_is_not_silently_ignored(tmp_path, monkeypatch):
    original = Path.read_text

    def missing(path, *args, **kwargs):
        if path.name == "luiz-herminio.txt":
            raise FileNotFoundError(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", missing)
    with pytest.raises(FileNotFoundError):
        create_product_app(tmp_path / "not-created.db", profile="luiz-herminio")


def test_empty_profile_asset_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: " ")
    with pytest.raises(ValueError, match="empty"):
        create_product_app(tmp_path / "not-created.db", profile="luiz-herminio")
