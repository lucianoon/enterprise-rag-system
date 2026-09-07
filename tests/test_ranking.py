"""Hand-calculated ranking contracts, independent of benchmark relevance labels."""

from math import log

import pytest

from enterprise_rag_system.ranking import BM25Index, normalize_tokens, reciprocal_rank_fusion


def test_analyzer_handles_composed_decomposed_and_missing_accents():
    assert normalize_tokens('AÇÃO, saúde REEMBOLSO_2026!') == ['acao', 'saude', 'reembolso', '2026']
    assert normalize_tokens('ac\u0327a\u0303o') == normalize_tokens('ação') == ['acao']
    assert normalize_tokens('東京 café') == ['東京', 'cafe']


def test_bm25_matches_hand_computed_idf_saturation_and_length_normalization():
    index = BM25Index({'short': 'a a', 'long': 'a b b b', 'other': 'c c'})
    scores = index.score('a a')
    idf = log(1 + (3 - 2 + 0.5) / (2 + 0.5))
    assert scores['short'] == pytest.approx(idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 2 / (8 / 3))))
    assert scores['long'] == pytest.approx(idf * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 4 / (8 / 3))))
    assert scores['short'] > scores['long']
    assert scores == index.score('a')
    assert 'other' not in scores


@pytest.mark.parametrize('documents', [{}, {'a': ''}, {'a': 'policy'}])
def test_bm25_empty_or_unknown_query_returns_no_matches(documents):
    index = BM25Index(documents)
    assert index.score('') == {}
    assert index.score('zzzz') == {}


def test_bm25_accent_insensitive_lookup():
    assert BM25Index({'a': 'Política de aprovação'}).score('politica aprovacao')['a'] > 0


def test_rrf_uses_positions_and_does_not_double_count_duplicates():
    scores = reciprocal_rank_fusion([['a', 'b', 'a'], ['b', 'c'], []])
    assert scores == pytest.approx({'a': 1 / 61, 'b': 1 / 62 + 1 / 61, 'c': 1 / 62})
    assert reciprocal_rank_fusion([]) == {}
