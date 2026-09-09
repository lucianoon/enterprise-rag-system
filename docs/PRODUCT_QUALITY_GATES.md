# Product quality gates

A model approving its own answer does not establish answer quality. The live evaluator
now also checks independently labelled content, expected evidence, citation numbering,
document scope, and a wall-clock latency budget. Labels must be created from the
source before the run, never inferred from the candidate answer being scored.

Example case (replace the document and chunk IDs with your labelled corpus):

```json
[
  {
    "question": "Qual é o prazo de reembolso?",
    "doc_id": "policy",
    "expected_abstention": false,
    "required_concepts": [["trinta dias", "30 dias"]],
    "forbidden_phrases": ["reembolso imediato"],
    "expected_chunk_ids": ["policy:0"],
    "max_latency_ms": 30000.0
  },
  {
    "question": "Qual é a senha atual do servidor?",
    "doc_id": "policy",
    "expected_abstention": true
  }
]
```

Each concept group requires at least one wording; at least one labelled chunk must be
cited. Matching ignores case, accents and repeated whitespace. These lexical checks
catch regressions but do not prove entailment or correctly interpret negation. Inspect
answers manually, include valid paraphrases before evaluation, and review labels when
chunking or document versions change. Do not tune labels merely to pass a failing run.

Run the existing evaluator with `PYTHONPATH=src` when the package is not installed:

```sh
PYTHONPATH=src python scripts/evaluate_product_answers.py \
  --token-file /path/to/token.txt --cases /path/to/cases.json \
  --output /path/to/new-report.json
```

Reports now contain `summary` and `results`, replacing the previous flat array.
Answerable cases without content/evidence labels are rejected. Output files are created
with mode 0600 and cannot overwrite a previous run. Reports include source excerpts.
API calls may incur provider costs and create query logs.

Summary includes false abstention and unsupported-answer rates, transport/processing
errors, explicit response denominators, and nearest-rank wall-clock p50/p95 latency.
Quality rates are null when no applicable response exists; transport errors cannot
produce a passing run. Latency includes failed requests. Exit status is nonzero on any
failed case. A small smoke set is not statistical evidence for a market-leading product.

## Recovery checks

`product_admin backup` uses SQLite online backup and verifies SQLite integrity before
reporting success. Validate a snapshot without schema migration:

```sh
python -m enterprise_rag_system.product_admin \
  --database /path/to/backup.sqlite3 verify-backup
```

The command validates SQLite integrity, supported registry schema, required tables and
head/version references; it prints counts, never documents or credentials. Unit tests
restore into a separate database and verify answers, cross-tenant rejection and retained
credential revocation. Never restore over a live registry or mix old WAL files.

This validates the registry, not a complete disaster-recovery bundle: original uploads
and Qdrant snapshots live separately. SQLite contains extracted document versions and
cached embeddings when populated, but Qdrant reconstruction and original-file recovery
need separate drills. A restored backup also restores its historical credential state;
reapply revocations made after that snapshot before allowing traffic.

A no-hit response (`generation_mode=abstained`, `verification=disabled`, no citations)
is also a valid evidence-based abstention: there is no generated draft to review.
It remains distinct from `abstained-unavailable` and other provider failures.
