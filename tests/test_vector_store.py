"""Vector store backend tests."""

import pytest

from enterprise_rag_system.vector_store import InMemoryVectorStore, build_vector_store


def test_in_memory_store_returns_best_match_first():
    store = InMemoryVectorStore()
    store.index(
        ["chunk_a", "chunk_b", "chunk_c"],
        [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]],
    )

    results = store.search([1.0, 0.0], top_k=2)

    assert results[0][0] == "chunk_a"
    assert results[0][1] == pytest.approx(1.0)
    assert len(results) == 2


def test_build_vector_store_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_STORE", "pinecone")

    with pytest.raises(ValueError, match="RAG_VECTOR_STORE"):
        build_vector_store()


def test_build_vector_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("RAG_VECTOR_STORE", raising=False)

    assert build_vector_store().name == "memory"


def test_qdrant_store_round_trip_in_memory_mode():
    pytest.importorskip("qdrant_client")
    from enterprise_rag_system.vector_store import QdrantVectorStore

    store = QdrantVectorStore(url=":memory:", collection="test_chunks")
    store.index(
        ["policy_refunds:0", "policy_security:0"],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    results = store.search([0.9, 0.1, 0.0], top_k=2)

    assert results[0][0] == "policy_refunds:0"
    assert results[0][1] > results[1][1]


@pytest.fixture(params=['memory', 'qdrant'])
def replacement_store(request):
    if request.param == 'memory':
        return InMemoryVectorStore()
    pytest.importorskip('qdrant_client')
    from enterprise_rag_system.vector_store import QdrantVectorStore

    return QdrantVectorStore(url=':memory:', collection='replacement_test')


@pytest.mark.parametrize('ids,vectors', [
    (['a'], []), (['a', 'a'], [[1.0], [2.0]]), ([' '], [[1.0]]),
    (['a'], [[]]), (['a', 'b'], [[1.0], [1.0, 2.0]]),
    (['a'], [[float('nan')]]), (['a'], [[float('inf')]]),
])
def test_invalid_replacement_preserves_previous_search(replacement_store, ids, vectors):
    replacement_store.index(['original'], [[1.0, 0.0]])
    before = replacement_store.search([1.0, 0.0], top_k=2)
    with pytest.raises(ValueError):
        replacement_store.index(ids, vectors)
    assert replacement_store.search([1.0, 0.0], top_k=2) == before


def test_replacement_removes_stale_ids_and_empty_index_clears_view(replacement_store):
    replacement_store.index(['old', 'gone'], [[1.0, 0.0], [0.0, 1.0]])
    replacement_store.index(['new'], [[0.0, 1.0]])
    assert [key for key, _ in replacement_store.search([1.0, 0.0], top_k=10)] == ['new']
    replacement_store.index([], [])
    assert replacement_store.search([1.0, 0.0], top_k=10) == []


def test_qdrant_failure_during_later_batch_preserves_old_generation(monkeypatch):
    pytest.importorskip('qdrant_client')
    from enterprise_rag_system.vector_store import QdrantVectorStore

    store = QdrantVectorStore(url=':memory:')
    store.index(['old'], [[1.0, 0.0]])
    active = store.active_collection
    upsert = store._client.upsert
    calls = 0

    def fail_second_batch(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs['wait'] is True
        assert store.search([1.0, 0.0], top_k=1)[0][0] == 'old'
        if calls == 2:
            raise TimeoutError('injected upload failure')
        return upsert(**kwargs)

    monkeypatch.setattr(store._client, 'upsert', fail_second_batch)
    with pytest.raises(TimeoutError):
        store.index([f'new-{i}' for i in range(257)], [[0.0, 1.0]] * 257)
    assert calls == 2
    assert store.active_collection == active
    assert store._client.collection_exists(active)
    assert store.search([1.0, 0.0], top_k=1)[0][0] == 'old'


@pytest.mark.parametrize('failure', ['acknowledged', 'count', 'create'])
def test_qdrant_does_not_activate_unverified_generation(monkeypatch, failure):
    pytest.importorskip('qdrant_client')
    from qdrant_client.models import CountResult, UpdateResult, UpdateStatus

    from enterprise_rag_system.vector_store import QdrantVectorStore

    store = QdrantVectorStore(url=':memory:')
    store.index(['old'], [[1.0]])
    before = store.active_collection
    if failure == 'acknowledged':
        monkeypatch.setattr(store._client, 'upsert', lambda **kw: UpdateResult(
            operation_id=1, status=UpdateStatus.ACKNOWLEDGED,
        ))
    elif failure == 'count':
        monkeypatch.setattr(store._client, 'count', lambda **kw: CountResult(count=0))
    else:
        monkeypatch.setattr(store._client, 'create_collection', lambda **kw: False)
    with pytest.raises(RuntimeError):
        store.index(['new'], [[1.0]])
    assert store.active_collection == before
    assert store.search([1.0], top_k=1)[0][0] == 'old'


@pytest.mark.parametrize("collection", ["x" * 210, "x" * 211, "x" * 255, "á" * 255])
def test_qdrant_generation_reserves_suffix_space(collection, monkeypatch):
    pytest.importorskip("qdrant_client")
    from enterprise_rag_system.vector_store import QdrantVectorStore

    store = QdrantVectorStore(url=":memory:", collection=collection)
    create = store._client.create_collection

    def bounded_create(**kwargs):
        assert len(kwargs["collection_name"].encode("utf-8")) <= 255
        return create(**kwargs)

    monkeypatch.setattr(store._client, "create_collection", bounded_create)
    store.index(["first"], [[1.0]])
    previous = store.active_collection
    store.index(["second"], [[1.0]])
    assert store.active_collection != previous
    assert store._client.collection_exists(previous)
    assert store.search([1.0], top_k=1)[0][0] == "second"
