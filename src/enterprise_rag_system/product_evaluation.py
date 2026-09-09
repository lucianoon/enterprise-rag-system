"""External, deterministic acceptance criteria; lexical checks are not semantic proof."""

import math
import re
import unicodedata
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


class AnswerCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    expected_abstention: bool
    # Each group requires at least one accepted wording.
    required_concepts: list[list[str]] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    max_latency_ms: float = Field(default=30000, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def meaningful_labels(self) -> Self:
        if not self.question.strip() or not self.doc_id.strip():
            raise ValueError("Question and document ID must not be blank")
        groups = self.required_concepts
        if not self.expected_abstention and (not groups or not self.expected_chunk_ids):
            raise ValueError("Answerable cases need labelled concepts and expected chunk IDs")
        if any(not g or any(not s.strip() for s in g) for g in groups):
            raise ValueError("Concept alternatives must be nonblank")
        if any(not s.strip() for s in self.forbidden_phrases + self.expected_chunk_ids):
            raise ValueError("Labels must be nonblank")
        return self


def assess(case: AnswerCase, response: dict, elapsed_ms: float) -> dict:
    failures = []
    abstained = response.get("abstained")
    answer = response.get("answer", "")
    citations = response.get("citations", [])
    verification = response.get("metadata", {}).get("verification")
    if type(abstained) is not bool or abstained != case.expected_abstention:
        failures.append("abstention_mismatch")
    if case.expected_abstention:
        no_retrieved_evidence = (
            response.get("metadata", {}).get("generation_mode") == "abstained"
            and verification == "disabled"
        )
        if (verification != "insufficient" and not no_retrieved_evidence) or citations:
            failures.append("not_evidence_based_abstention")
    else:
        if verification != "supported" or not citations or not answer.strip():
            failures.append("unverified_answer")
        text = normalized(answer)
        if any(
            not any(normalized(term) in text for term in group) for group in case.required_concepts
        ):
            failures.append("missing_expected_concept")
        if any(normalized(term) in text for term in case.forbidden_phrases):
            failures.append("forbidden_claim")
        if not set(case.expected_chunk_ids) & {c.get("chunk_id") for c in citations}:
            failures.append("missing_expected_evidence")
        if any(c.get("doc_id") != case.doc_id for c in citations):
            failures.append("wrong_document")
        markers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
        numbers = {c.get("number") for c in citations}
        if not markers or markers != numbers or len(numbers) != len(citations):
            failures.append("citation_mismatch")
    if not math.isfinite(elapsed_ms) or elapsed_ms > case.max_latency_ms:
        failures.append("latency_budget_exceeded")
    return {"passed": not failures, "failures": failures, "elapsed_ms": elapsed_ms}


def summarize(results: list[dict]) -> dict:
    answerable = [r for r in results if not r["case"]["expected_abstention"]]
    unanswerable = [r for r in results if r["case"]["expected_abstention"]]
    valid_answerable = [
        r for r in answerable if type(r.get("response", {}).get("abstained")) is bool
    ]
    valid_unanswerable = [
        r for r in unanswerable if type(r.get("response", {}).get("abstained")) is bool
    ]
    timings = sorted(r["elapsed_ms"] for r in results if math.isfinite(r["elapsed_ms"]))

    def rate(rows, predicate):
        return sum(predicate(r) for r in rows) / len(rows) if rows else None

    return {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "answerable_responses": len(valid_answerable),
        "unanswerable_responses": len(valid_unanswerable),
        "false_abstention_rate": rate(
            valid_answerable, lambda r: r.get("response", {}).get("abstained") is True
        ),
        "unsupported_answer_rate": rate(
            valid_unanswerable, lambda r: r.get("response", {}).get("abstained") is False
        ),
        "error_rate": rate(results, lambda r: bool(r.get("error_type"))),
        "latency_p50_ms": timings[math.ceil(len(timings) * 0.5) - 1] if timings else None,
        "latency_p95_ms": timings[math.ceil(len(timings) * 0.95) - 1] if timings else None,
    }
