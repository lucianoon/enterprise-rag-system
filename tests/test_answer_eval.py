"""Answer faithfulness judge tests."""

import pytest

from enterprise_rag_system.answer_eval import (
    HeuristicAnswerJudge,
    build_answer_judge,
)
from enterprise_rag_system.models import Chunk, SearchResult


def _results() -> list[SearchResult]:
    chunk = Chunk(
        chunk_id="policy_refunds:0",
        doc_id="policy_refunds",
        title="Refund Policy",
        text=(
            "Refund requests must include the order ID, customer email and "
            "purchase date. Refunds over 500 USD require manager approval."
        ),
    )
    return [SearchResult(chunk=chunk, lexical_score=1.0, vector_score=1.0, hybrid_score=1.0)]


def test_grounded_answer_scores_high():
    judgement = HeuristicAnswerJudge().judge(
        "What must a refund request include?",
        "Refund requests must include the order ID, customer email and purchase date.",
        _results(),
    )

    assert judgement.faithfulness == 1.0
    assert judgement.unsupported_claims == []
    assert judgement.judge_mode == "heuristic"


def test_fabricated_answer_scores_low():
    fabricated = "Refunds are always processed within 24 hours via cryptocurrency wallets."
    judgement = HeuristicAnswerJudge().judge("How fast are refunds?", fabricated, _results())

    assert judgement.faithfulness == 0.0
    assert fabricated in judgement.unsupported_claims


def test_mixed_answer_flags_only_unsupported_sentences():
    answer = (
        "Refund requests must include the order ID, customer email and purchase date. "
        "All refunds are paid in bitcoin within one hour."
    )
    judgement = HeuristicAnswerJudge().judge("Refund process?", answer, _results())

    assert judgement.faithfulness == 0.5
    assert len(judgement.unsupported_claims) == 1
    assert "bitcoin" in judgement.unsupported_claims[0]


def test_empty_context_scores_zero():
    judgement = HeuristicAnswerJudge().judge("Anything?", "Some claim.", [])

    assert judgement.faithfulness == 0.0


def test_build_answer_judge_defaults_to_heuristic(monkeypatch):
    monkeypatch.delenv("RAG_JUDGE_MODE", raising=False)

    assert build_answer_judge().mode == "heuristic"


def test_build_answer_judge_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("RAG_JUDGE_MODE", "vibes")

    with pytest.raises(ValueError, match="RAG_JUDGE_MODE"):
        build_answer_judge()
