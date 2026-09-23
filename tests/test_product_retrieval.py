"""Product lexical retrieval: cached snapshot index, invalidated by content changes."""

import pytest
from fastapi.testclient import TestClient

from enterprise_rag_system.product_api import create_product_app
from enterprise_rag_system.product_retrieval import (
    LexicalIndexCache,
    build_snapshot,
    lexical_question,
    snapshot_key,
)


def row(doc_id="a", title="Viagens", text="Solicite reembolso pelo portal financeiro."):
    return {"doc_id": doc_id, "title": title, "text": text, "revision": 1}


def test_snapshot_key_is_order_independent_and_content_sensitive():
    rows = [row("a"), row("b", text="Outro texto")]
    assert snapshot_key("t", rows) == snapshot_key("t", list(reversed(rows)))
    assert snapshot_key("t", rows) != snapshot_key("u", rows)
    assert snapshot_key("t", rows) != snapshot_key("t", [row("a"), row("b", text="Mudou")])
    assert snapshot_key("t", rows) != snapshot_key("t", rows[:1])
    # Field boundaries are delimited: moving text between fields changes the key.
    assert snapshot_key("t", [row(title="ab", text="c")]) != snapshot_key(
        "t", [row(title="a", text="bc")]
    )


def test_cache_reuses_and_invalidates_snapshots():
    cache = LexicalIndexCache(maxsize=2)
    first = cache.get("t", [row()])
    assert cache.get("t", [row()]) is first
    assert (cache.hits, cache.misses) == (1, 1)
    changed = cache.get("t", [row(text="Novo prazo de reembolso.")])
    assert changed is not first
    assert cache.misses == 2
    cache.get("t", [row("c")])  # evicts the least recently used entry (first)
    assert len(cache) == 2
    assert cache.get("t", [row()]) is not first
    with pytest.raises(ValueError):
        LexicalIndexCache(maxsize=0)


def test_snapshot_rank_orders_positive_scores_with_id_ties():
    snapshot = build_snapshot([row("b"), row("a"), row("z", text="Nada relacionado.")])
    scores, selected = snapshot.rank("reembolso", 5)
    assert [c.doc_id for c in selected] == ["a", "b"]
    assert "z:0" not in scores


def test_lexical_question_drops_function_words_with_fallback():
    assert lexical_question("Qual é o prazo de reembolso?") == "prazo reembolso"
    assert lexical_question("o que é?") == "o que é?"


def test_product_query_reuses_index_until_the_corpus_changes(tmp_path):
    app = create_product_app(tmp_path / "registry.db")
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + app.state.registry.issue_user("t", "u", "admin")}
    cache = app.state.lexical_cache
    document = {"title": "Viagens", "text": "Solicite reembolso pelo portal.",
                "expected_revision": 0}
    client.put("/documents/viagens", headers=auth, json=document).raise_for_status()

    def ask():
        response = client.post("/query", headers=auth, json={"question": "reembolso"})
        response.raise_for_status()
        return response.json()

    assert "portal" in ask()["answer"]
    assert "portal" in ask()["answer"]
    assert (cache.hits, cache.misses) == (1, 1)
    update = {**document, "text": "Solicite reembolso pelo aplicativo.", "expected_revision": 1}
    client.put("/documents/viagens", headers=auth, json=update).raise_for_status()
    answer = ask()["answer"]
    assert "aplicativo" in answer and "portal" not in answer
    assert cache.misses == 2
