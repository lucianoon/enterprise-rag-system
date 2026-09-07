"""Behavioral tests for trustworthy, tenant-scoped pilot measurements."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_store import DocumentInput, Registry


@pytest.fixture
def pilot(tmp_path):
    app = create_product_app(tmp_path / "registry.db")
    store = app.state.registry
    keys = {
        name: store.issue_user(tenant, user, role)
        for name, tenant, user, role in [
            ("admin", "alpha", "owner", "admin"),
            ("reader", "alpha", "reader", "reader"),
            ("other", "beta", "reader", "admin"),
        ]
    }
    return TestClient(app), store, keys


def auth(keys, name="reader"):
    return {"Authorization": "Bearer " + keys[name]}


def query(client, keys, name="reader", question="reembolso"):
    result = client.post("/query", headers=auth(keys, name), json={"question": question})
    result.raise_for_status()
    return result.json()["query_id"]


def test_feedback_is_bound_to_real_query_and_owner(pilot):
    client, _, keys = pilot
    qid = query(client, keys)
    body = {"rating": "not_helpful", "reason": "missing_information"}
    for name in ["admin", "other"]:
        assert (
            client.put(f"/queries/{qid}/feedback", headers=auth(keys, name), json=body).status_code
            == 404
        )
    assert (
        client.put("/queries/" + "f" * 32 + "/feedback", headers=auth(keys), json=body).status_code
        == 404
    )
    result = client.put(f"/queries/{qid}/feedback", headers=auth(keys), json=body)
    assert result.status_code == 200
    for _ in range(25):
        assert (
            client.put(f"/queries/{qid}/feedback", headers=auth(keys), json=body).status_code == 200
        )
    assert (
        client.put(
            f"/queries/{qid}/feedback", headers=auth(keys), json={"rating": "helpful"}
        ).status_code
        == 200
    )
    summary = client.get("/quality", headers=auth(keys, "admin")).json()
    assert summary["queries"] == summary["rated_queries"] == summary["helpful"] == 1
    assert summary["not_helpful"] == 0
    assert summary["negative_reasons"] == {}
    assert client.get("/quality", headers=auth(keys)).status_code == 403
    assert client.get("/quality", headers=auth(keys, "other")).json()["queries"] == 0


def test_measurements_do_not_store_prompt_answer_or_sources(pilot):
    client, store, keys = pilot
    store.write_document(
        keys["admin"],
        "classified-id",
        DocumentInput(
            title="CONFIDENTIAL-TITLE",
            text="secret-payroll-token",
            visibility="tenant",
            expected_revision=0,
        ),
    )
    qid = query(client, keys, question="secret-payroll-token PRIVATE-QUESTION")
    with store.connection() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM query_events")]
    serialized = json.dumps(rows)
    for secret in [
        "CONFIDENTIAL-TITLE",
        "secret-payroll-token",
        "PRIVATE-QUESTION",
        "classified-id",
        keys["reader"],
    ]:
        assert secret not in serialized
    assert rows[0]["id"] == qid
    assert rows[0]["citation_count"] == 1
    for body in [
        {"rating": "helpful", "comment": "PRIVATE-QUESTION"},
        {"rating": "helpful", "reason": "other"},
        {"rating": "not_helpful", "reason": "private arbitrary text"},
    ]:
        assert (
            client.put(f"/queries/{qid}/feedback", headers=auth(keys), json=body).status_code == 422
        )


def test_revocation_applies_to_feedback_and_inflight_answer(pilot, monkeypatch):
    client, store, keys = pilot
    qid = query(client, keys)
    store.revoke("alpha", "reader")
    assert (
        client.put(
            f"/queries/{qid}/feedback", headers=auth(keys), json={"rating": "helpful"}
        ).status_code
        == 401
    )
    store.write_document(
        keys["admin"],
        "travel",
        DocumentInput(title="Travel", text="reembolso", expected_revision=0),
    )
    llm = TestClient(create_product_app(store.path, generation="llm"))

    def revoke_during_generation(*args, **kwargs):
        store.revoke("alpha", "owner")
        return "reembolso [1]"

    monkeypatch.setattr(
        "enterprise_rag_system.product_api.llm_client.complete", revoke_during_generation
    )
    assert (
        llm.post("/query", headers=auth(keys, "admin"), json={"question": "reembolso"}).status_code
        == 401
    )


def test_quality_denominators_percentiles_and_reasons(pilot):
    client, store, keys = pilot
    empty = client.get("/quality", headers=auth(keys, "admin")).json()
    assert empty["feedback_coverage"] is None
    assert empty["helpful_rate_among_rated"] is None
    assert empty["latency_ms"] == {"p50": None, "p95": None}
    ids = [
        store.record_query(keys["reader"], 1, mode, latency, count)
        for mode, latency, count in [
            ("extractive", 10, 1),
            ("abstained", 20, 0),
            ("extractive-provider-fallback", 90, 1),
        ]
    ]
    store.feedback(keys["reader"], ids[0], "helpful", None)
    store.feedback(keys["reader"], ids[1], "not_helpful", "missing_information")
    stats = client.get("/quality?days=7", headers=auth(keys, "admin")).json()
    assert stats["queries"] == 3
    assert stats["feedback_coverage"] == pytest.approx(2 / 3)
    assert stats["helpful_rate_among_rated"] == 0.5
    assert stats["without_sources"] == 1
    assert stats["negative_reasons"] == {"missing_information": 1}
    assert stats["generation_modes"]["extractive-provider-fallback"] == 1
    assert stats["latency_ms"] == {"p50": 20, "p95": 90}
    assert client.get("/quality?days=31", headers=auth(keys, "admin")).status_code == 422


def test_retention_expiry_and_maintenance_do_not_remove_documents(pilot, monkeypatch):
    client, store, keys = pilot
    now = [10000000.0]
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: now[0])
    qid = query(client, keys)
    store.write_document(
        keys["admin"], "policy", DocumentInput(title="Policy", text="retained", expected_revision=0)
    )
    now[0] += 31 * 86400
    assert client.get("/quality", headers=auth(keys, "admin")).json()["queries"] == 0
    assert (
        client.put(
            f"/queries/{qid}/feedback", headers=auth(keys), json={"rating": "helpful"}
        ).status_code
        == 404
    )
    assert store.prune_measurements() == 1
    assert store.prune_measurements() == 0
    assert store.documents(keys["admin"])[2][0]["text"] == "retained"


def test_record_retention_is_bounded_and_tenant_scoped(pilot, monkeypatch):
    _, store, keys = pilot
    monkeypatch.setattr("enterprise_rag_system.product_store.time", lambda: 20000.0)
    other = store.record_query(keys["other"], 0, "abstained", 1, 0)
    with store.connection(write=True) as db:
        db.executemany(
            "INSERT INTO query_events VALUES(?,?,?,?,?,?,?,?,NULL,NULL)",
            [(str(i), "alpha", "reader", float(i), 0, "abstained", 1, 0) for i in range(10000)],
        )
    newest = store.record_query(keys["reader"], 0, "abstained", 2, 0)
    with store.connection() as db:
        assert (
            db.execute("SELECT count(*) FROM query_events WHERE tenant='alpha'").fetchone()[0]
            == 10000
        )
        assert db.execute("SELECT 1 FROM query_events WHERE id=?", (newest,)).fetchone()
        assert db.execute("SELECT 1 FROM query_events WHERE id='0'").fetchone() is None
        assert db.execute("SELECT 1 FROM query_events WHERE id=?", (other,)).fetchone()
    assert store.quality(keys["admin"])["sample_at_capacity"] is True


def test_v1_migration_preserves_data_and_backup(pilot, tmp_path):
    _, store, keys = pilot
    store.write_document(
        keys["admin"], "policy", DocumentInput(title="Policy", text="original", expected_revision=0)
    )
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE query_events")
        db.execute("PRAGMA user_version=1")
    # Two workers starting together must not partially migrate the registry.
    with ThreadPoolExecutor(max_workers=2) as pool:
        upgraded = list(pool.map(lambda _: Registry(store.path), range(2)))
    assert upgraded[0].documents(keys["admin"])[2][0]["revision"] == 1
    qid = upgraded[0].record_query(keys["reader"], 1, "extractive", 10, 1)
    upgraded[1].feedback(keys["reader"], qid, "helpful", None)
    backup = tmp_path / "backup.db"
    upgraded[1].backup(backup)
    restored = Registry(backup)
    assert restored.quality(keys["admin"])["helpful"] == 1
    assert restored.documents(keys["admin"])[2][0]["text"] == "original"
    with restored.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
