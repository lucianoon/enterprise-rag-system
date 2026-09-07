"""Document loading and chunking."""

import json
from collections.abc import Iterable
from pathlib import Path

from enterprise_rag_system.models import Chunk, Document


def load_jsonl(path: Path) -> list[Document]:
    """Load documents from JSONL."""
    docs = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                document = Document.model_validate(json.loads(line))
                if not all(value.strip() for value in (
                    document.doc_id, document.title, document.text,
                )):
                    raise ValueError("Corpus documents need non-empty ids, titles and text")
                if document.doc_id in seen:
                    raise ValueError("Corpus must have unique document ids")
                seen.add(document.doc_id)
                docs.append(document)
    if not docs:
        raise ValueError("Corpus must be non-empty")
    return docs


def chunk_documents(documents: Iterable[Document], max_words: int = 80) -> list[Chunk]:
    """Split documents into word-count chunks."""
    if max_words < 1:
        raise ValueError("max_words must be positive")
    chunks = []
    for doc in documents:
        words = doc.text.split()
        for index in range(0, len(words), max_words):
            text = " ".join(words[index:index + max_words])
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}:{index // max_words}",
                    doc_id=doc.doc_id,
                    title=doc.title,
                    text=text,
                )
            )
    return chunks

