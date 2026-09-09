import sqlite3

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_backup import verify_backup
from enterprise_rag_system.product_store import DocumentInput, Registry


def test_restore_preserves_answers_tenant_isolation_and_revocation(tmp_path):
    source = Registry(tmp_path / "source.db")
    owner = source.issue_user("a", "owner", "admin")
    other = source.issue_user("b", "owner", "admin")
    revoked = source.issue_user("a", "former", "reader")
    source.revoke("a", "former")
    source.write_document(
        owner,
        "policy",
        DocumentInput(
            title="Reembolso", text="O prazo de reembolso é trinta dias.", expected_revision=0
        ),
    )
    destination = tmp_path / "restored.db"
    source.backup(destination)
    original = destination.read_bytes()
    assert verify_backup(destination)["counts"]["heads"] == 1
    assert destination.read_bytes() == original
    assert destination.stat().st_mode & 0o777 == 0o600
    # A second process opens only the snapshot; source edits cannot affect it.
    source.write_document(
        owner,
        "policy",
        DocumentInput(title="Reembolso", text="O prazo mudou para dez dias.", expected_revision=1),
    )
    client = TestClient(create_product_app(destination))

    def query(token):
        return client.post(
            "/query",
            headers={"Authorization": "Bearer " + token},
            json={"question": "Qual prazo de reembolso?", "doc_id": "policy"},
        )

    result = query(owner)
    assert result.status_code == 200
    assert "trinta dias" in result.json()["answer"]
    assert query(other).status_code == 404
    assert query(revoked).status_code == 401
    with pytest.raises(FileExistsError):
        source.backup(destination)


def test_backup_validation_rejects_corruption_and_dangling_heads(tmp_path):
    path = tmp_path / "db"
    Registry(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO heads VALUES ('t', 'missing', 1)")
    with pytest.raises(ValueError, match="missing versions"):
        verify_backup(path)
    corrupt = tmp_path / "corrupt"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        verify_backup(corrupt)
    with pytest.raises(ValueError, match="does not exist"):
        verify_backup(tmp_path / "absent")
