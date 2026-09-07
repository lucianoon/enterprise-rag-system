"""Reject unusable corpora before embedding or indexing begins."""

import json

import pytest

from enterprise_rag_system.ingestion import chunk_documents, load_jsonl


@pytest.mark.parametrize('documents', [
    [], [{'doc_id': '', 'title': 't', 'text': 'body'}],
    [{'doc_id': 'a', 'title': ' ', 'text': 'body'}],
    [{'doc_id': 'a', 'title': 't', 'text': '\t'}],
    [{'doc_id': 'a', 'title': 't', 'text': 'first'},
     {'doc_id': 'a', 'title': 't', 'text': 'second'}],
])
def test_invalid_corpus_is_rejected(tmp_path, documents):
    path = tmp_path / 'corpus.jsonl'
    path.write_text(''.join(json.dumps(d) + '\n' for d in documents))
    with pytest.raises(ValueError, match='Corpus'):
        load_jsonl(path)


@pytest.mark.parametrize('max_words', [0, -1])
def test_nonpositive_chunk_size_is_rejected(max_words):
    with pytest.raises(ValueError, match='positive'):
        chunk_documents([], max_words=max_words)
