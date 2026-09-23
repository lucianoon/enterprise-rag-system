"""One analyzer for every pipeline: accents must never split a word."""

import pytest

from enterprise_rag_system import answer_eval, ranking, retrieval
from enterprise_rag_system.embeddings import HashingEmbedder
from enterprise_rag_system.models import Chunk
from enterprise_rag_system.retrieval import HybridRetriever, Reranker
from enterprise_rag_system.tokenization import FUNCTION_WORDS, content_terms, fold, tokenize
from enterprise_rag_system.vector_store import InMemoryVectorStore


@pytest.mark.parametrize(
    "text,expected",
    [
        ("política", ["politica"]),
        ("Aprovação da DIRETORIA", ["aprovacao", "da", "diretoria"]),
        ("ac\u0327a\u0303o", ["acao"]),  # decomposed input folds like precomposed
        ("REEMBOLSO_2026, v2!", ["reembolso", "2026", "v2"]),
        ("Straße", ["strasse"]),  # casefold, not lower()
        ("ﬁscal", ["fiscal"]),  # NFKD compatibility ligature
        ("東京 café", ["東京", "cafe"]),
        ("", []),
    ],
)
def test_tokenize_folds_without_breaking_words(text, expected):
    assert tokenize(text) == expected


def test_fold_is_idempotent():
    folded = fold("Informações PÚBLICAS")
    assert fold(folded) == folded == "informacoes publicas"


def test_every_pipeline_uses_the_same_analyzer():
    assert retrieval.tokenize is tokenize
    assert ranking.normalize_tokens is tokenize


def test_function_words_are_already_folded():
    assert all(tokenize(word) == [word] for word in FUNCTION_WORDS)
    assert content_terms("Qual é a política de reembolso?") == ["politica", "reembolso"]
    assert content_terms("Qual a política?", stopwords=["politica"]) == ["qual", "a"]


def test_hashing_embedder_is_accent_and_case_insensitive():
    embedder = HashingEmbedder()
    assert embedder.embed_query("POLÍTICA de ação") == embedder.embed_query("politica de acao")


_CHUNKS = [
    Chunk(
        chunk_id="viagem:0",
        doc_id="viagem",
        title="Política de viagens",
        text="A aprovação prévia do gestor é obrigatória para viagens internacionais.",
    ),
    Chunk(
        chunk_id="ferias:0",
        doc_id="ferias",
        title="Férias",
        text="Solicite as férias com trinta dias de antecedência no portal.",
    ),
]


@pytest.mark.parametrize("mode", ["lexical", "hybrid", "bm25"])
def test_unaccented_query_matches_accented_document_in_every_mode(mode):
    retriever = HybridRetriever(
        _CHUNKS, embedder=HashingEmbedder(), vector_store=InMemoryVectorStore()
    )
    results = retriever.search("aprovacao previa", top_k=1, mode=mode)
    assert results[0].chunk.doc_id == "viagem"
    assert results[0].lexical_score > 0


def test_legacy_lexical_score_no_longer_matches_accent_fragments():
    # The old ``[a-z0-9]+`` analyzer produced "pol"/"tica" fragments that matched
    # unrelated words; the whole folded word must be required now.
    retriever = HybridRetriever(
        _CHUNKS, embedder=HashingEmbedder(), vector_store=InMemoryVectorStore()
    )
    scores = {r.chunk.doc_id: r.lexical_score for r in retriever.search("tica", mode="lexical")}
    assert scores == {"viagem": 0.0, "ferias": 0.0}


def test_reranker_title_bonus_ignores_accents_and_case():
    retriever = HybridRetriever(
        _CHUNKS, embedder=HashingEmbedder(), vector_store=InMemoryVectorStore()
    )
    results = retriever.search("regras da POLITICA DE VIAGENS", top_k=2)
    reranked = Reranker().rerank("regras da POLITICA DE VIAGENS", results)
    top = reranked[0]
    assert top.chunk.doc_id == "viagem"
    assert top.rerank_score == pytest.approx(top.hybrid_score + 3 / 5 + 0.25, abs=1e-4)


def test_reranker_title_bonus_requires_whole_words():
    chunk = Chunk(chunk_id="x:0", doc_id="x", title="Férias", text="texto")
    retriever = HybridRetriever([chunk], embedder=HashingEmbedder(),
                                vector_store=InMemoryVectorStore())
    results = retriever.search("feriasx", top_k=1)
    reranked = Reranker().rerank("feriasx", results)
    assert reranked[0].rerank_score == results[0].hybrid_score


def test_answer_judge_tokens_fold_accents():
    assert answer_eval._content_tokens("A aprovação é obrigatória") == {
        "aprovacao", "e", "obrigatoria",
    }


def test_tfidf_uses_the_shared_analyzer():
    pytest.importorskip("sklearn")
    from enterprise_rag_system.embeddings import TfidfEmbedder

    embedder = TfidfEmbedder()
    embedder.fit(["Política de aprovação", "Férias no portal"])
    vocabulary = set(embedder._vectorizer.vocabulary_)
    assert {"politica", "aprovacao", "ferias"} <= vocabulary
    assert not {"pol", "tica"} & vocabulary
