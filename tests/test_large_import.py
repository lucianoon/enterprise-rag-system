import time
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_rag_system.file_import import parse
from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_vectors import ProductVectors


def test_large_text_not_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_LARGE_IMPORT", "true")
    source = tmp_path / "large.txt"
    text = "Conteúdo completo. " * 5000
    source.write_text(text)
    assert parse(source)["text"] == text.strip()


def test_streaming_background_job_permissions_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_PRODUCT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(
        ProductVectors, "_openai", lambda self, texts: [[1.0] + [0.0] * 1535 for _ in texts]
    )
    # Keep the real job/persistence/vector path; replace only the platform parser process.
    import json

    def parse_process(args, stdout, **kwargs):
        stdout.write(json.dumps({"text": Path(args[-1]).read_text(), "ocr_pages": []}).encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("enterprise_rag_system.large_import.subprocess.run", parse_process)
    app = create_product_app(tmp_path / "db")
    client = TestClient(app)
    store = app.state.registry
    token = store.issue_user("a", "owner", "admin")
    other = store.issue_user("b", "other", "admin")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"}
    content = ("Conteúdo completo com instruções sobre backups. " * 1000).encode()
    assert client.post("/uploads?filename=x.txt", content=content).status_code == 401
    response = client.post("/uploads?filename=x.txt", headers=headers, content=content)
    assert response.status_code == 202, response.text
    job = response.json()["job_id"]
    for _ in range(100):
        state = client.get("/uploads/" + job, headers=headers).json()
        if state["state"] in {"ready", "failed"}:
            break
        time.sleep(0.01)
    assert state["state"] == "ready", state
    saved = client.get("/documents/" + job, headers=headers).json()
    assert saved["text"].encode() == content
    assert state["characters"] > 32000
    assert (
        client.get("/uploads/" + job, headers={"Authorization": "Bearer " + other}).status_code
        == 404
    )
    assert (tmp_path / "uploads" / (job + ".txt")).read_bytes() == content


def test_interrupted_job_is_visible_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_PRODUCT_RETRIEVAL", "hybrid")
    app = create_product_app(tmp_path / "db")
    token = app.state.registry.issue_user("a", "owner", "admin")
    with app.state.registry.connection(write=True) as db:
        db.execute(
            "INSERT INTO import_jobs(id,tenant,owner,filename,path,state) "
            "VALUES('job','a','owner','manual.pdf','unused','indexing')"
        )
    restarted = TestClient(create_product_app(tmp_path / "db"))
    headers = {"Authorization": "Bearer " + token}
    assert restarted.get("/uploads/job", headers=headers).json()["state"] == "interrupted"
    assert restarted.get("/uploads", headers=headers).json()["jobs"] == ["job"]
