"""Pilot boundary tests: persistence, authorization, concurrency and safe generation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app, valid_citations
from enterprise_rag_system.product_store import DocumentInput, Registry, StoreError


@pytest.fixture
def pilot(tmp_path):
    app = create_product_app(tmp_path / "registry.db")
    store = app.state.registry
    keys = {
        "admin": store.issue_user("alpha", "admin", "admin"),
        "editor": store.issue_user("alpha", "editor", "editor"),
        "reader": store.issue_user("alpha", "reader", "reader"),
        "other": store.issue_user("beta", "admin", "admin"),
    }
    return TestClient(app), store, keys


def headers(keys, user="admin"):
    return {"Authorization": "Bearer " + keys[user]}


def value(**changes):
    return {
        "title": "Viagens",
        "text": "Solicite reembolso pelo portal financeiro.",
        "expected_revision": 0,
        **changes,
    }


def test_no_global_key_or_client_tenant_can_bypass_auth(pilot, monkeypatch):
    client, _, keys = pilot
    monkeypatch.setenv("RAG_API_KEY", "legacy-key")
    assert client.get("/documents", headers={"X-API-Key": "legacy-key"}).status_code == 401
    assert client.get("/documents", headers={"Authorization": "Bearer fake"}).status_code == 401
    assert (
        client.post(
            "/query",
            headers=headers(keys),
            json={
                "question": "reembolso",
                "tenant": "beta",
            },
        ).status_code
        == 422
    )
    assert client.get("/me", headers=headers(keys, "other")).json()["tenant"] == "beta"


def test_tenant_and_document_permissions_apply_before_retrieval_and_generation(pilot):
    client, _, keys = pilot
    assert client.put("/documents/secret", headers=headers(keys), json=value()).status_code == 200
    for user in ["reader", "other"]:
        assert client.get("/documents", headers=headers(keys, user)).json()["documents"] == []
        assert client.get("/documents/secret", headers=headers(keys, user)).status_code == 404
        response = client.post(
            "/query", headers=headers(keys, user), json={"question": "reembolso"}
        )
        assert response.json()["abstained"] is True
        assert response.json()["citations"] == []
        assert "portal financeiro" not in response.text
    granted = value(expected_revision=1, readers=["reader"])
    client.put("/documents/secret", headers=headers(keys), json=granted).raise_for_status()
    response = client.post(
        "/query", headers=headers(keys, "reader"), json={"question": "reembolso"}
    )
    assert response.json()["citations"][0]["revision"] == 2
    assert "portal financeiro" in response.json()["answer"]
    assert (
        client.put("/documents/secret", headers=headers(keys, "reader"), json=granted).status_code
        == 403
    )
    assert client.get("/audit", headers=headers(keys, "reader")).status_code == 403


def test_revocation_and_rotation_take_effect_across_store_instances(pilot):
    client, store, keys = pilot
    second = Registry(store.path)
    second.revoke("alpha", "reader")
    assert client.get("/documents", headers=headers(keys, "reader")).status_code == 401
    rotated = second.issue_user("alpha", "admin", "admin")
    assert client.get("/documents", headers=headers(keys)).status_code == 401
    assert (
        client.get("/documents", headers={"Authorization": "Bearer " + rotated}).status_code == 200
    )
    with second.connection() as db:
        assert keys["admin"] not in str([tuple(r) for r in db.execute("SELECT * FROM users")])


def test_acl_revocation_has_no_stale_retrieval_cache(pilot):
    client, _, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value(readers=["reader"]))
    assert client.post(
        "/query", headers=headers(keys, "reader"), json={"question": "reembolso"}
    ).json()["citations"]
    client.put("/documents/a", headers=headers(keys), json=value(expected_revision=1))
    assert client.post(
        "/query", headers=headers(keys, "reader"), json={"question": "reembolso"}
    ).json()["abstained"]


def test_restart_retains_docs_and_versions_and_backup_is_restorable(pilot, tmp_path):
    client, store, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value()).raise_for_status()
    restart = TestClient(create_product_app(store.path))
    assert restart.get("/documents/a", headers=headers(keys)).json()["text"] == value()["text"]
    backup = tmp_path / "backup.db"
    store.backup(backup)
    restored = TestClient(create_product_app(backup))
    assert restored.get("/documents/a", headers=headers(keys)).json()["revision"] == 1
    with pytest.raises(FileExistsError):
        store.backup(backup)
    assert backup.stat().st_mode & 0o777 == 0o600


def test_stale_writes_delete_restore_and_history(pilot):
    client, _, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value(visibility="tenant"))
    assert client.put("/documents/a", headers=headers(keys), json=value()).status_code == 409
    client.put(
        "/documents/a",
        headers=headers(keys),
        json=value(
            text="Política atualizada.",
            expected_revision=1,
        ),
    ).raise_for_status()
    assert (
        client.delete("/documents/a?expected_revision=1", headers=headers(keys)).status_code == 409
    )
    client.delete("/documents/a?expected_revision=2", headers=headers(keys)).raise_for_status()
    assert client.get("/documents/a", headers=headers(keys)).status_code == 404
    assert len(client.get("/documents/a/history", headers=headers(keys)).json()["versions"]) == 3
    client.post(
        "/documents/a/restore",
        headers=headers(keys),
        json={
            "revision": 1,
            "expected_revision": 3,
        },
    ).raise_for_status()
    response = client.get("/documents/a", headers=headers(keys)).json()
    assert response["revision"] == 4
    assert response["text"] == value()["text"]
    assert response["visibility"] == "private"  # Never reinstate historical ACL.
    assert client.get("/documents/a", headers=headers(keys, "reader")).status_code == 404


def test_simultaneous_edits_have_one_winner(pilot):
    _, store, keys = pilot
    store.write_document(keys["admin"], "a", DocumentInput(**value()))

    def edit(text):
        try:
            return Registry(store.path).write_document(
                keys["admin"],
                "a",
                DocumentInput(
                    **value(text=text, expected_revision=1),
                ),
            )["revision"]
        except StoreError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(edit, ["one", "two"])) == [2, 409]


def test_query_limits_persist_across_restarts(pilot, monkeypatch):
    client, store, keys = pilot
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: 120.0)
    for _ in range(30):
        assert (
            client.post("/query", headers=headers(keys), json={"question": "travel"}).status_code
            == 200
        )
    restart = TestClient(create_product_app(store.path))
    response = restart.post("/query", headers=headers(keys), json={"question": "travel"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: 180.0)
    assert (
        restart.post("/query", headers=headers(keys), json={"question": "travel"}).status_code
        == 200
    )


def test_no_private_text_or_questions_in_audit(pilot):
    client, _, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value())
    client.post("/query", headers=headers(keys), json={"question": "pergunta privada"})
    events = client.get("/audit", headers=headers(keys)).text
    assert "pergunta privada" not in events and "portal financeiro" not in events
    assert "document_saved" in events and "query" in events
    assert (
        client.get("/audit", headers=headers(keys, "other")).json()["events"][0]["action"]
        == "credential_rotated"
    )


def test_body_and_field_limits(pilot):
    client, _, keys = pilot
    assert client.post("/query", headers=headers(keys), content=b"x" * 131073).status_code == 413
    assert (
        client.post("/query", headers=headers(keys), json={"question": "a" * 4001}).status_code
        == 422
    )
    assert client.post("/query", headers=headers(keys), json={"question": " "}).status_code == 422
    assert (
        client.put("/documents/a", headers=headers(keys), json=value(text=" ")).status_code == 422
    )
    assert (
        client.put(
            "/documents/a", headers=headers(keys), json=value(readers=["unknown"])
        ).status_code
        == 422
    )


def test_llm_citations_are_checked_and_unauthorized_context_is_never_sent(pilot, monkeypatch):
    _, store, keys = pilot
    store.write_document(keys["admin"], "a", DocumentInput(**value(readers=["reader"])))
    store.write_document(keys["other"], "b", DocumentInput(**value(text="REEMBOLSO SECRET BETA")))
    app = TestClient(create_product_app(store.path, generation="llm"))
    seen = []

    def complete(system, prompt, **kwargs):
        seen.append(prompt)
        return "Uma afirmação [999]."

    monkeypatch.setattr("enterprise_rag_system.product_api.llm_client.complete", complete)
    response = app.post("/query", headers=headers(keys, "reader"), json={"question": "reembolso"})
    assert response.json()["metadata"]["generation_mode"] == "extractive-invalid-citations"
    assert "SECRET BETA" not in seen[0]
    monkeypatch.setattr(
        "enterprise_rag_system.product_api.llm_client.complete", lambda *a, **kw: "Portal [1]."
    )
    response = app.post("/query", headers=headers(keys, "reader"), json={"question": "reembolso"})
    assert response.json()["metadata"]["generation_mode"] == "llm-structurally-checked"
    assert not valid_citations("Texto sem fonte.", 1)
    assert not valid_citations("Outra afirmação.\n\nTexto [1].", 1)


def test_future_schema_is_not_silently_downgraded(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema"):
        Registry(path)


def test_product_does_not_construct_demo_or_qdrant_on_start(tmp_path):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "RAG_PRODUCT_DB": str(tmp_path / "product.db"),
        "PYTHONPATH": os.pathsep.join(sys.path),
        "RAG_DOCUMENTS_PATH": "/missing/source",
        "RAG_VECTOR_STORE": "not-a-backend",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from enterprise_rag_system.api import app; assert app.title.endswith('piloto')",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_deleted_documents_require_admin_and_tombstones_cannot_be_restored(pilot):
    client, _, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value(visibility="tenant"))
    client.delete("/documents/a?expected_revision=1", headers=headers(keys)).raise_for_status()
    assert (
        client.get("/documents?include_deleted=true", headers=headers(keys, "reader")).status_code
        == 403
    )
    result = client.get("/documents?include_deleted=true", headers=headers(keys)).json()
    assert result["documents"][0]["deleted"] is True
    assert (
        client.post(
            "/documents/a/restore",
            headers=headers(keys),
            json={
                "revision": 2,
                "expected_revision": 2,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/documents/a/restore",
            headers=headers(keys, "reader"),
            json={
                "revision": 1,
                "expected_revision": 2,
            },
        ).status_code
        == 403
    )


def test_unprivileged_mutations_and_foreign_history_are_blocked(pilot):
    client, _, keys = pilot
    client.put("/documents/a", headers=headers(keys), json=value())
    assert (
        client.put(
            "/documents/a", headers=headers(keys, "editor"), json=value(expected_revision=1)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            "/documents/a?expected_revision=1", headers=headers(keys, "reader")
        ).status_code
        == 403
    )
    assert (
        client.delete(
            "/documents/a?expected_revision=1", headers=headers(keys, "other")
        ).status_code
        == 404
    )
    assert (
        client.get("/documents/a/history", headers=headers(keys, "other")).json()["versions"] == []
    )
    assert (
        client.post(
            "/documents/a/restore",
            headers=headers(keys, "other"),
            json={
                "revision": 1,
                "expected_revision": 1,
            },
        ).status_code
        == 404
    )


def test_write_rate_limit_is_independent_of_query_budget(pilot, monkeypatch):
    client, _, keys = pilot
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: 1000.0)
    for i in range(20):
        client.put(
            "/documents/a", headers=headers(keys), json=value(expected_revision=i)
        ).raise_for_status()
    assert (
        client.put(
            "/documents/a", headers=headers(keys), json=value(expected_revision=20)
        ).status_code
        == 429
    )
    assert (
        client.post("/query", headers=headers(keys), json={"question": "reembolso"}).status_code
        == 200
    )


def test_structural_citation_fallback_on_provider_failure(pilot, monkeypatch):
    _, store, keys = pilot
    store.write_document(keys["admin"], "a", DocumentInput(**value()))

    def failure(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("enterprise_rag_system.product_api.llm_client.complete", failure)
    client = TestClient(create_product_app(store.path, generation="llm"))
    result = client.post("/query", headers=headers(keys), json={"question": "reembolso"}).json()
    assert result["metadata"]["generation_mode"] == "extractive-provider-fallback"
    assert result["citations"][0]["doc_id"] == "a"


def test_frontend_security_headers_and_no_credential_persistence(pilot):
    client, _, _ = pilot
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "nonce=" in response.text
    assert "localStorage" not in response.text and "sessionStorage" not in response.text
    assert "innerHTML" not in response.text
    assert client.get("/ready").json() == {"status": "ready"}


def test_product_bm25_preserves_the_frozen_corporate_ranking(pilot, monkeypatch):
    import itertools
    import json

    from enterprise_rag_system.benchmark import DEFAULT_DATA

    client, store, keys = pilot
    ticks = itertools.count(1)
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: next(ticks) * 60.0)
    for line in (DEFAULT_DATA / "corpus.jsonl").read_text().splitlines():
        doc = json.loads(line)
        store.write_document(
            keys["admin"],
            doc["doc_id"],
            DocumentInput(
                title=doc["title"],
                text=doc["text"],
                expected_revision=0,
            ),
        )
    baseline = json.loads((DEFAULT_DATA / "baseline-bm25-rrf-hashing-test.json").read_text())
    expected = next(r for r in baseline["rows"] if r["strategy"] == "bm25" and r["top_k"] == 3)
    questions = {
        c["query_id"]: c["question"]
        for c in map(json.loads, (DEFAULT_DATA / "queries.jsonl").read_text().splitlines())
    }
    for case in expected["per_query"]:
        result = client.post(
            "/query",
            headers=headers(keys),
            json={
                "question": questions[case["query_id"]],
                "top_k": 3,
            },
        )
        assert result.status_code == 200
        assert [c["doc_id"] for c in result.json()["citations"]] == case["retrieved_doc_ids"]


def test_registry_cli_issues_revokes_and_backs_up(tmp_path, monkeypatch, capsys):
    import sys

    from enterprise_rag_system.product_admin import main

    path = tmp_path / "cli.db"
    base = ["product_admin", "--database", str(path)]
    monkeypatch.setattr(
        sys, "argv", [*base, "issue-user", "--tenant", "t", "--user", "u", "--role", "admin"]
    )
    main()
    token = capsys.readouterr().out.strip()
    assert Registry(path).documents(token)[0].user == "u"
    monkeypatch.setattr(sys, "argv", [*base, "backup", str(tmp_path / "backup.db")])
    main()
    assert (tmp_path / "backup.db").exists()
    monkeypatch.setattr(sys, "argv", [*base, "revoke-user", "--tenant", "t", "--user", "u"])
    main()
    with pytest.raises(StoreError):
        Registry(path).documents(token)


def test_blank_product_database_never_falls_back_to_demo():
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import enterprise_rag_system.api"],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), "RAG_PRODUCT_DB": " "},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "RAG_PRODUCT_DB must not be blank" in result.stderr


def test_registry_rejects_unrelated_database(tmp_path):
    import sqlite3

    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
    with pytest.raises(ValueError, match="not an empty registry"):
        Registry(path)
