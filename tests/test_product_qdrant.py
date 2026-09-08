"""Real Qdrant engine checks using the SDK local backend, without provider calls."""

import pytest

from enterprise_rag_system.product_qdrant import ProductQdrant


def test_authorized_ids_tenants_and_persistence(tmp_path):
    qdrant = pytest.importorskip("qdrant_client")
    client = qdrant.QdrantClient(path=str(tmp_path / "qdrant"))
    index = ProductQdrant("fixture", 3, client=client)
    index.prepare()
    index.put(
        "alpha", {"current": [1.0, 0.0, 0.0], "old": [1.0, 0.0, 0.0], "private": [1.0, 0.0, 0.0]}
    )
    index.put("beta", {"current": [1.0, 0.0, 0.0]})
    assert set(index.search("alpha", ["current"], [1.0, 0.0, 0.0])) == {"current"}
    assert index.search("alpha", [], [1.0, 0.0, 0.0]) == {}
    assert index.present("gamma", ["current"]) == set()
    assert index.point_id("alpha", "current") != index.point_id("beta", "current")
    client.close()
    client = qdrant.QdrantClient(path=str(tmp_path / "qdrant"))
    reopened = ProductQdrant("fixture", 3, client=client)
    assert reopened.present("alpha", ["current"]) == {"current"}
    client.close()


def test_incompatible_collection_fails_without_replacement():
    qdrant = pytest.importorskip("qdrant_client")
    from qdrant_client import models as m

    client = qdrant.QdrantClient(":memory:")
    index = ProductQdrant("fixture", 3, client=client)
    client.create_collection(
        index.collection, vectors_config=m.VectorParams(size=2, distance=m.Distance.COSINE)
    )
    with pytest.raises(ValueError, match="Incompatible"):
        index.prepare()
    assert client.get_collection(index.collection).config.params.vectors.size == 2
    client.close()
