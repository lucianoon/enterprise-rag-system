import pytest

from enterprise_rag_system.product_evaluation import AnswerCase, assess, summarize


def case(**kwargs):
    return AnswerCase(
        question="Prazo?",
        doc_id="policy",
        expected_abstention=False,
        required_concepts=[["trinta dias", "30 dias"]],
        expected_chunk_ids=["policy:0"],
        forbidden_phrases=["sempre correto"],
        **kwargs,
    )


def answer(text="O prazo é trinta dias [1].", **kwargs):
    return {
        "answer": text,
        "abstained": False,
        "metadata": {"verification": "supported"},
        "citations": [{"number": 1, "doc_id": "policy", "chunk_id": "policy:0"}],
        **kwargs,
    }


@pytest.mark.parametrize(
    "text,failure",
    [
        ("O prazo é dez dias [1].", "missing_expected_concept"),
        ("Trinta dias, sempre correto [1].", "forbidden_claim"),
        ("Trinta dias [2].", "citation_mismatch"),
    ],
)
def test_self_approval_does_not_override_external_labels(text, failure):
    assert failure in assess(case(), answer(text), 100)["failures"]


def test_correct_answer_must_meet_evidence_and_latency():
    assert assess(case(), answer(), 100)["passed"]
    assert not assess(case(), answer(), 30001)["passed"]
    wrong = answer(citations=[{"number": 1, "doc_id": "other", "chunk_id": "other:0"}])
    assert set(assess(case(), wrong, 100)["failures"]) == {
        "wrong_document",
        "missing_expected_evidence",
    }


def test_error_is_not_a_successful_abstention():
    c = AnswerCase(question="Segredo?", doc_id="policy", expected_abstention=True)
    r = {"abstained": True, "citations": [], "metadata": {"verification": "unavailable"}}
    assert not assess(c, r, 100)["passed"]
    r["metadata"]["verification"] = "insufficient"
    assert assess(c, r, 100)["passed"]


def test_labels_are_required_and_metrics_have_explicit_denominators():
    with pytest.raises(ValueError):
        AnswerCase(question="Prazo?", doc_id="p", expected_abstention=False)
    rows = [
        {
            "case": {"expected_abstention": False},
            "passed": False,
            "response": {"abstained": True},
            "elapsed_ms": 100,
        }
    ]
    summary = summarize(rows)
    assert summary["false_abstention_rate"] == 1
    assert summary["unsupported_answer_rate"] is None
    assert summary["answerable_cases"] == 1


def test_transport_errors_do_not_look_like_zero_quality_errors():
    summary = summarize(
        [
            {
                "case": {"expected_abstention": False},
                "passed": False,
                "elapsed_ms": 10,
                "error_type": "URLError",
            }
        ]
    )
    assert summary["false_abstention_rate"] is None
    assert summary["answerable_responses"] == 0
    assert summary["error_rate"] == 1


def test_no_retrieved_evidence_is_distinct_from_reviewer_failure():
    c = AnswerCase(question="Faturamento?", doc_id="policy", expected_abstention=True)
    response = {
        "abstained": True,
        "citations": [],
        "metadata": {"generation_mode": "abstained", "verification": "disabled"},
    }
    assert assess(c, response, 100)["passed"]
    response["metadata"]["generation_mode"] = "abstained-unavailable"
    assert not assess(c, response, 100)["passed"]
