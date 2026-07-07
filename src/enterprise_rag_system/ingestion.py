"""Document loading and chunking."""

import json
from pathlib import Path
from typing import Iterable, List

from enterprise_rag_system.models import Chunk, Document


def load_jsonl(path: Path) -> List[Document]:
    """Load documents from JSONL."""
    docs = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                docs.append(Document.model_validate(json.loads(line)))
    return docs


def chunk_documents(documents: Iterable[Document], max_words: int = 80) -> List[Chunk]:
    """Split documents into word-count chunks."""
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

