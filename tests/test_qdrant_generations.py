"""Generation contracts against both Qdrant local and an opt-in real server.

CI supplies RAG_QDRANT_TEST_URL for its disposable service. Each test uses a
unique namespace and deletes only collections it created in that namespace.
"""

import os
import uuid

import pytest


@pytest.fixture(params=['local', 'server'])
def stores(request):
    pytest.importorskip('qdrant_client')
    from enterprise_rag_system.vector_store import QdrantVectorStore

    url = ':memory:' if request.param == 'local' else os.getenv('RAG_QDRANT_TEST_URL')
    if not url:
        pytest.skip('Set RAG_QDRANT_TEST_URL to exercise a disposable server')
    namespace = 'rag_test_' + uuid.uuid4().hex
    first = QdrantVectorStore(url=url, collection=namespace)
    second = QdrantVectorStore(url=':memory:', collection=namespace)
    second._client.close()
    second._client = first._client
    try:
        yield first, second
    finally:
        # Cleanup is confined to a test-owned UUID namespace, never application data.
        for collection in first._client.get_collections().collections:
            if (collection.name == namespace
                    or collection.name.startswith(namespace + '__generation_')):
                first._client.delete_collection(collection.name)
        first._client.close()


def test_instances_with_same_namespace_keep_their_own_generations(stores):
    first, second = stores
    first.index(['shared-id'], [[1.0, 0.0]])
    old = first.active_collection
    second.index(['shared-id'], [[0.0, 1.0]])
    assert second.active_collection != old
    assert first.search([1.0, 0.0], top_k=1)[0][1] == pytest.approx(1.0)
    assert second.search([1.0, 0.0], top_k=1)[0][1] == pytest.approx(0.0)
    assert first._client.collection_exists(old)


def test_existing_legacy_collection_is_never_modified(stores):
    from qdrant_client.models import Distance, PointStruct, VectorParams

    store, _ = stores
    store._client.create_collection(
        collection_name=store.collection,
        vectors_config=VectorParams(size=2, distance=Distance.COSINE),
    )
    store._client.upsert(
        collection_name=store.collection,
        points=[PointStruct(id=1, vector=[1.0, 0.0], payload={'sentinel': 'preserve'})],
        wait=True,
    )
    store.index(['new'], [[0.0, 1.0]])
    original = store._client.retrieve(collection_name=store.collection, ids=[1])[0]
    assert original.payload == {'sentinel': 'preserve'}
    assert store._client.count(collection_name=store.collection, exact=True).count == 1


def test_replacement_supports_new_dimensions_and_retains_old_collection(stores):
    store, _ = stores
    store.index(['old'], [[1.0, 0.0]])
    old = store.active_collection
    store.index(['new'], [[1.0, 0.0, 0.0]])
    assert store.search([1.0, 0.0, 0.0], top_k=1)[0][0] == 'new'
    assert store._client.count(collection_name=old, exact=True).count == 1
    store.index([], [])
    assert store.active_collection is None
    assert store.search([1.0, 0.0, 0.0], top_k=1) == []
    assert store._client.count(collection_name=old, exact=True).count == 1


def test_reader_keeps_old_generation_until_writer_finishes(stores, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    store, _ = stores
    store.index(['old'], [[1.0, 0.0]])
    previous = store.active_collection
    entered = Event()
    resume = Event()
    original = store._client.upsert

    def paused_upload(**kwargs):
        entered.set()
        if not resume.wait(timeout=10):
            raise TimeoutError('test did not resume upload')
        return original(**kwargs)

    monkeypatch.setattr(store._client, 'upsert', paused_upload)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(store.index, ['new'], [[0.0, 1.0]])
        try:
            assert entered.wait(timeout=10)
            assert store.active_collection == previous
            assert store.search([1.0, 0.0], top_k=1)[0][0] == 'old'
        finally:
            resume.set()
        pending.result(timeout=10)
    assert store.active_collection != previous
    assert store.search([0.0, 1.0], top_k=1)[0][0] == 'new'
