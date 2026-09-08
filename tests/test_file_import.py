"""Import contracts: extraction, limits and authorization before parsing."""

import base64
import zipfile

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.file_import import MAX_BYTES, extract, parse
from enterprise_rag_system.product_api import create_product_app


def test_docx_paragraphs_and_table_cells(tmp_path):
    source = tmp_path / "sample.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Pastor evangélico</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Comunidade</w:t></w:r></w:p></w:tc>
</w:tr></w:tbl></w:body></w:document>""",
        )
    assert parse(source)["text"] == "Pastor evangélico\nComunidade"


@pytest.mark.parametrize(
    "data,name", [(b"hello", "x.exe"), (b"", "x.txt"), (b"x" * (MAX_BYTES + 1), "x.pdf")]
)
def test_file_limits(data, name):
    with pytest.raises(ValueError):
        extract(data, name)


def test_no_silent_truncation(tmp_path):
    source = tmp_path / "long.txt"
    source.write_text("a" * 32001)
    with pytest.raises(ValueError, match="32 mil"):
        parse(source)


def test_docx_entities_rejected(tmp_path):
    source = tmp_path / "bad.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "<!DOCTYPE a><a/>")
    with pytest.raises(ValueError, match="XML"):
        parse(source)


def test_auth_and_preview_do_not_persist(tmp_path, monkeypatch):
    app = create_product_app(tmp_path / "db")
    client = TestClient(app)
    store = app.state.registry
    reader = store.issue_user("local", "reader", "reader")
    editor = store.issue_user("local", "editor", "editor")
    payload = {"filename": "a.txt", "content": base64.b64encode(b"hello").decode()}
    calls = []

    def extraction(data, name):
        calls.append(name)
        return {"text": data.decode(), "ocr_pages": []}

    monkeypatch.setattr("enterprise_rag_system.product_api.extract", extraction)
    assert client.post("/imports/extract", json=payload).status_code == 401
    assert (
        client.post(
            "/imports/extract", json=payload, headers={"Authorization": "Bearer " + reader}
        ).status_code
        == 403
    )
    assert calls == []
    headers = {"Authorization": "Bearer " + editor}
    response = client.post("/imports/extract", json=payload, headers=headers)
    assert response.json()["text"] == "hello"
    assert client.get("/documents", headers=headers).json()["documents"] == []
    payload["content"] = "@invalid"
    assert client.post("/imports/extract", json=payload, headers=headers).status_code == 422
