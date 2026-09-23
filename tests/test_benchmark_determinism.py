"""The benchmark must rank identically in every process and on every CPU.

The BM25/RRF gate compares per-query rankings against frozen references with
zero tolerance, so any hidden source of nondeterminism (hash seed, set/dict
order, SIMD-dependent sorting) shows up as a flaky CI failure.
"""

import os
import subprocess
import sys

import pytest

from enterprise_rag_system.embeddings import TfidfEmbedder

pytest.importorskip("sklearn")

# Runs the CI gate's configuration (test split, BM25 and RRF, both offline
# backends) and prints every ranking and mean metric with full float precision.
SCRIPT = r"""
import json
from enterprise_rag_system.benchmark import DEFAULT_DATA, run_benchmark

output = {}
for backend in ("hashing", "tfidf"):
    report = run_benchmark(
        DEFAULT_DATA / "corpus.jsonl", DEFAULT_DATA / "queries.jsonl",
        split="test", backend=backend, strategies=("bm25", "rrf"), repeats=1,
    )
    output[backend] = [
        [
            row.strategy, row.top_k,
            row.mean_metrics.model_dump() if row.mean_metrics else None,
            [[case.query_id, case.retrieved_doc_ids] for case in row.per_query],
        ]
        for row in report.rows
    ]
print(json.dumps(output, sort_keys=True))
"""


def _cpu_has(feature: str) -> bool:
    try:
        from numpy._core._multiarray_umath import __cpu_features__
    except ImportError:  # pragma: no cover - older NumPy layout
        return False
    return bool(__cpu_features__.get(feature))


def _run_benchmark(**env_overrides: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "NPY_DISABLE_CPU_FEATURES"}
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT], env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=600, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_benchmark_rankings_do_not_depend_on_hash_seed_or_simd_dispatch():
    variants = [{"PYTHONHASHSEED": "0"}, {"PYTHONHASHSEED": "4242"}]
    # NumPy's unstable argsort breaks ties differently with AVX-512 enabled;
    # scikit-learn's max_features used it, so different CI runners froze
    # different TF-IDF vocabularies. Compare both dispatches when available.
    if _cpu_has("X86_V4"):
        variants.append({"PYTHONHASHSEED": "7", "NPY_DISABLE_CPU_FEATURES": "X86_V4"})

    outputs = [_run_benchmark(**variant) for variant in variants]

    for variant, output in zip(variants[1:], outputs[1:], strict=True):
        assert output == outputs[0], f"Benchmark output changed under {variant}"


def test_tfidf_vocabulary_breaks_frequency_ties_by_term():
    corpus = ["zeta alpha", "beta gamma", "alpha delta"]
    forward = TfidfEmbedder(max_features=2)
    backward = TfidfEmbedder(max_features=2)

    forward.fit(corpus)
    backward.fit(corpus[::-1])

    # "alpha" is the only term seen twice; every other unigram/bigram ties at
    # one occurrence, and the alphabetically first of them fills the last slot.
    assert sorted(forward._vectorizer.vocabulary_) == ["alpha", "alpha delta"]
    assert forward._vectorizer.vocabulary_ == backward._vectorizer.vocabulary_


def test_tfidf_keeps_every_term_under_the_limit_and_rejects_bad_input():
    embedder = TfidfEmbedder()
    embedder.fit(["refund order", "order date"])

    assert embedder.dims == 5  # refund, order, date, "refund order", "order date"
    with pytest.raises(ValueError, match="max_features"):
        TfidfEmbedder(max_features=0)
    with pytest.raises(ValueError, match="empty"):
        TfidfEmbedder().fit(["the and of"])
