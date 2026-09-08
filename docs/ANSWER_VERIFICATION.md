# Evidence review for generated answers

Set `RAG_PRODUCT_VERIFY=true` with LLM generation to review each generated answer
against the authorized retrieved excerpts. The product Compose configuration enables it.

The reviewer returns a structured verdict and supporting quotations. For a supported
answer, the API checks that each reported claim occurs in the answer, each quotation
occurs verbatim in its source, and each paragraph has evidence with the corresponding
citation. Quotations retain the source language. An invalid review gets one retry.

A `revise` verdict allows one rewrite followed by another review. An `insufficient`
verdict, an unapproved rewrite, or an unavailable reviewer produces an abstention and
no answer citations. The UI distinguishes unavailable verification from insufficient
evidence. `metadata.verification` reports `disabled`, `supported`, `revise`,
`insufficient`, or `unavailable`; `abstained` remains the consumer-facing answer flag.

This is model-assisted checking, not proof of truth. Exact quotation matching checks
provenance, not semantic entailment. A model can miss an unsupported claim, accept a
weak quotation, or incorrectly reject a correct answer. Missing retrieval context can
also cause abstention. Review uses the configured generation provider/model and adds
one call normally, up to five calls including retries and a rewrite. Measure latency,
false abstentions, and citation support on representative documents before rollout.

Tests cover invented evidence, original-language quotation repair, citation placement,
reviewer failure, insufficient evidence, and re-review after rewriting. Live-corpus
checks must also include answerable and unanswerable questions; a small smoke test is
not a market benchmark.

## Repeatable live-corpus smoke test

Create a JSON array with `question`, `doc_id`, and boolean `expected_abstention` for
each labelled case. Use document IDs accessible to the evaluation credential. Run:

```sh
python scripts/evaluate_product_answers.py \
  --url http://127.0.0.1:8002 \
  --token-file /path/to/product-token.txt \
  --cases /path/to/cases.json \
  --output /path/to/report.json
```

The runner requires `supported` with citations for answerable cases, and `insufficient`
without citations for unanswerable cases. Provider failure never counts as a correct
abstention. Exit status is nonzero on any failure. Results require human inspection for
semantic correctness; labels and machine verdicts alone do not establish answer quality.
It uses the live API, incurs configured provider costs, and creates normal query logs.
The report includes document excerpts and should retain the corpus access restrictions.
