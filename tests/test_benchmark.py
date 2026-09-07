"""Metric examples and end-to-end reproducibility checks for the benchmark CLI."""

import json
import sys
from math import log2

import pytest

from enterprise_rag_system import llm_client
from enterprise_rag_system.benchmark import (
    DEFAULT_DATA,
    BenchmarkReport,
    compare_reports,
    load_cases,
    main,
    ranking_metrics,
    run_benchmark,
)


def test_ranking_metrics_with_missed_and_late_relevant_documents():
    metrics = ranking_metrics(["wrong", "a", "other"], ["a", "b"], 3)

    assert metrics is not None
    assert metrics.recall == 0.5
    assert metrics.precision == pytest.approx(1 / 3)
    assert metrics.mrr == 0.5
    assert metrics.ndcg == pytest.approx((1 / log2(3)) / (1 + 1 / log2(3)))


def test_duplicate_chunks_cannot_inflate_document_relevance():
    metrics = ranking_metrics(["a", "a", "b"], ["a", "b"], 3)

    assert metrics is not None
    assert metrics.recall == 1.0
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.ndcg == pytest.approx(1.5 / (1 + 1 / log2(3)))


def test_metrics_respect_cutoff_and_keep_unanswerable_queries_separate():
    missed = ranking_metrics(["wrong", "a"], ["a"], 1)
    assert missed is not None
    assert missed.model_dump() == {"recall": 0.0, "precision": 0.0, "mrr": 0.0, "ndcg": 0.0}
    assert ranking_metrics(["a"], [], 1) is None
    with pytest.raises(ValueError, match="positive"):
        ranking_metrics([], ["a"], 0)


@pytest.fixture
def dataset(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    queries = tmp_path / "queries.jsonl"
    corpus.write_text(
        json.dumps({"doc_id": "a", "title": "Refund", "text": "Refund order."}) + "\n"
    )
    cases = [
        {"query_id": "q1", "question": "refund", "relevant_doc_ids": ["a"],
         "split": "dev", "category": "direct"},
        {"query_id": "q2", "question": "unknown topic", "relevant_doc_ids": [],
         "split": "dev", "category": "unanswerable"},
        {"query_id": "q3", "question": "order", "relevant_doc_ids": ["a"],
         "split": "test", "category": "direct"},
    ]
    queries.write_text("".join(json.dumps(case) + "\n" for case in cases))
    return corpus, queries


def test_benchmark_never_invokes_generation_or_external_backends(dataset, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A retrieval-only benchmark must not invoke a model")

    monkeypatch.setattr(llm_client, "complete", forbidden)
    monkeypatch.setenv("RAG_LLM_MODE", "llm")
    monkeypatch.setenv("RAG_VECTOR_STORE", "qdrant")
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "sentence-transformer")
    report = run_benchmark(*dataset, top_ks=(1, 3), repeats=2)

    assert report.document_count == 1
    assert report.query_count == 2
    assert len(report.rows) == 8
    for row in report.rows:
        assert row.answerable_count == 1
        assert row.unanswerable_count == 1
        assert row.mean_metrics is not None
        assert row.mean_metrics.recall == 1.0
        assert row.unanswerable_return_rate == 1.0
        assert row.latency_p95_ms >= row.latency_median_ms >= 0
    replay = run_benchmark(*dataset, top_ks=(1, 3), repeats=1)
    assert compare_reports(replay, report) == []
    assert BenchmarkReport.model_validate_json(report.model_dump_json()) == report


def test_test_split_is_selected_explicitly(dataset):
    report = run_benchmark(*dataset, split="test", top_ks=(1,), repeats=1)

    assert report.query_count == 1
    assert all(row.unanswerable_count == 0 for row in report.rows)
    assert all(row.unanswerable_return_rate is None for row in report.rows)
    assert all(row.per_query[0].query_id == "q3" for row in report.rows)


def test_tfidf_backend_runs_offline(dataset):
    pytest.importorskip("sklearn")
    report = run_benchmark(*dataset, backend="tfidf", top_ks=(1,), repeats=1)

    assert report.embedding_backend == "tfidf"
    assert int(report.environment["embedding_dimensions"]) > 0
    assert report.environment["scikit-learn"] != "not-used"


def test_unanswerable_only_split_does_not_claim_perfect_quality(dataset):
    corpus, queries = dataset
    case = json.loads(queries.read_text().splitlines()[1])
    queries.write_text(json.dumps(case) + "\n")

    report = run_benchmark(corpus, queries, top_ks=(1,), repeats=1)

    assert all(row.mean_metrics is None for row in report.rows)
    assert compare_reports(report, report) == []


@pytest.mark.parametrize("mutation,expected", [
    ({"question": "  "}, "Empty or duplicate"),
    ({"relevant_doc_ids": ["missing"]}, "Unknown document"),
    ({"relevant_doc_ids": ["a", "a"]}, "Duplicate relevance"),
])
def test_invalid_labels_are_rejected(dataset, mutation, expected):
    _, queries = dataset
    case = json.loads(queries.read_text().splitlines()[0])
    case.update(mutation)
    queries.write_text(json.dumps(case) + "\n")

    with pytest.raises(ValueError, match=expected):
        load_cases(queries, {"a"})


def test_duplicate_question_across_splits_is_rejected(dataset):
    _, queries = dataset
    cases = [json.loads(line) for line in queries.read_text().splitlines()]
    cases[2]["question"] = "  REFUND  "
    queries.write_text("".join(json.dumps(case) + "\n" for case in cases))

    with pytest.raises(ValueError, match="duplicate"):
        load_cases(queries, {"a"})


@pytest.mark.parametrize("options", [
    {"repeats": 0}, {"max_words": 0}, {"top_ks": ()}, {"top_ks": (0,)},
    {"backend": "remote"}, {"split": "absent"},
])
def test_invalid_benchmark_configuration_is_rejected(dataset, options):
    with pytest.raises(ValueError):
        run_benchmark(*dataset, **options)


@pytest.mark.parametrize("contents", ["", '{"doc_id":"a","title":"t","text":" "}\n'])
def test_empty_corpus_or_document_is_rejected(dataset, contents):
    corpus, queries = dataset
    corpus.write_text(contents)
    with pytest.raises(ValueError, match="Corpus"):
        run_benchmark(corpus, queries)


def test_comparison_detects_metric_regressions_and_allows_explicit_tolerance(dataset):
    before = run_benchmark(*dataset, top_ks=(1,), repeats=1)
    after = before.model_copy(deep=True)
    assert after.rows[0].mean_metrics is not None
    after.rows[0].mean_metrics.recall -= 0.01

    assert compare_reports(after, before) == ["lexical@1 recall: 1.000000 -> 0.990000"]
    assert compare_reports(after, before, max_regression=0.02) == []
    with pytest.raises(ValueError, match="max_regression"):
        compare_reports(after, before, max_regression=float("nan"))


def test_comparison_rejects_changed_data_and_missing_matrix_rows(dataset):
    before = run_benchmark(*dataset, top_ks=(1,), repeats=1)
    changed = before.model_copy(update={"queries_sha256": "different"})
    with pytest.raises(ValueError, match="queries_sha256"):
        compare_reports(changed, before)
    changed = before.model_copy(update={"rows": before.rows[:-1]})
    with pytest.raises(ValueError, match="matrix"):
        compare_reports(changed, before)
    changed = before.model_copy(deep=True)
    changed.rows[0].per_query.pop()
    with pytest.raises(ValueError, match="queries"):
        compare_reports(changed, before)


def test_cli_rejects_changed_data_and_keeps_current_artifact(
    dataset, tmp_path, monkeypatch, capsys
):
    corpus, queries = dataset
    baseline = run_benchmark(corpus, queries, top_ks=(1,), repeats=1)
    extra = {"doc_id": "b", "title": "Unrelated", "text": "Unrelated content."}
    corpus.write_text(corpus.read_text() + json.dumps(extra) + "\n")
    baseline_path = tmp_path / "baseline.json"
    # A data mismatch must fail closed, rather than silently passing.
    baseline_path.write_text(baseline.model_dump_json())
    output = tmp_path / "results" / "report.json"
    command = [
        "benchmark",
        "--corpus", str(corpus), "--queries", str(queries), "--repeats", "1",
        "--top-k", "1", "--output", str(output), "--baseline", str(baseline_path),
    ]
    monkeypatch.setattr(sys, "argv", command)
    with pytest.raises(SystemExit) as failure:
        main()

    assert failure.value.code == 2
    assert "corpus_sha256" in capsys.readouterr().err
    assert output.exists()


def test_cli_returns_failure_for_quality_regression(dataset, tmp_path, monkeypatch, capsys):
    corpus, queries = dataset
    extra = {"doc_id": "b", "title": "Unrelated", "text": "Unrelated content."}
    corpus.write_text(corpus.read_text() + json.dumps(extra) + "\n")
    cases = [json.loads(line) for line in queries.read_text().splitlines()]
    cases[0]["question"] = "unrelated"
    queries.write_text("".join(json.dumps(case) + "\n" for case in cases))
    baseline = run_benchmark(corpus, queries, top_ks=(1,), repeats=1)
    assert baseline.rows[0].mean_metrics is not None
    assert baseline.rows[0].mean_metrics.recall == 0.0
    # Simulate the reference score of a previous, better retrieval implementation.
    baseline.rows[0].mean_metrics.recall = 1.0
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(baseline.model_dump_json())
    output = tmp_path / "report.json"

    monkeypatch.setattr(sys, "argv", [
        "benchmark",
        "--corpus", str(corpus), "--queries", str(queries), "--repeats", "1",
        "--top-k", "1", "--baseline", str(baseline_path), "--output", str(output),
    ])
    with pytest.raises(SystemExit) as failure:
        main()

    assert failure.value.code == 1
    assert "lexical@1 recall: 1.000000 -> 0.000000" in capsys.readouterr().err
    assert output.exists()


def test_bundled_benchmark_has_disjoint_queries_and_valid_labels():
    from enterprise_rag_system.ingestion import load_jsonl

    documents = load_jsonl(DEFAULT_DATA / "corpus.jsonl")
    cases = load_cases(DEFAULT_DATA / "queries.jsonl", {d.doc_id for d in documents})

    assert len(documents) == 30
    assert len(cases) == 80
    for split in ("dev", "test"):
        selected = [case for case in cases if case.split == split]
        assert len(selected) == 40
        assert sum(not case.relevant_doc_ids for case in selected) == 5
        assert sum(len(case.relevant_doc_ids) > 1 for case in selected) == 5
