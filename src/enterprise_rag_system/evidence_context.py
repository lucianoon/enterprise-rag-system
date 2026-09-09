"""Bounded context windows over an already authorized document snapshot."""

from enterprise_rag_system.models import Chunk


def expand_context(selected: list[Chunk], chunks: list[Chunk]) -> tuple[list[Chunk], dict]:
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    positions = {c.chunk_id: i for group in by_doc.values() for i, c in enumerate(group)}
    expanded = []
    members = {}
    covered = set()
    for hit in selected:
        if hit.chunk_id in covered:
            continue
        group = by_doc[hit.doc_id]
        index = positions[hit.chunk_id]
        window = group[max(0, index - 1) : index + 2]
        ids = [c.chunk_id for c in window]
        covered.update(ids)
        members[hit.chunk_id] = ids
        expanded.append(hit.model_copy(update={"text": " ".join(c.text for c in window)}))
    return expanded, members
