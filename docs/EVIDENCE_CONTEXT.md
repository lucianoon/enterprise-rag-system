# Inspectable evidence and bounded neighboring context

LLM product queries retain the existing 80-word retrieval index and expand selected
hits with one preceding and one following chunk from the same authorized document
snapshot. The result is at most 240 words per source; hits already covered by an
expanded window are skipped. Ranking and persisted embeddings remain unchanged.
Extractive queries preserve their original retrieval behavior and frozen baseline.

Generation and evidence review receive the same expanded text returned in citations.
`chunk_id` identifies the original retrieval hit; `context_chunk_ids` lists all chunks
in the cited window. Consumers evaluating evidence should distinguish the retrieval
anchor from the complete quoted context. Expansion can add irrelevant information and
increase model input tokens; measure answer quality and latency on the target corpus.

The source card's “Conferir no texto extraído” button loads:

`GET /documents/{doc_id}/evidence?revision=1&chunk_index=2`

The endpoint authenticates the caller and checks current document access before
returning the hit and its neighbors. A changed revision returns 409, an inaccessible
or deleted document returns 404, and an invalid credential returns 401. It does not
expose historical text under changed permissions. The UI renders text as text nodes,
marks the anchor chunk, and discards results if the source view is no longer current.

This is a viewer for extracted text. Existing ingestion does not preserve reliable
page/character coordinates in the original PDF; `location_kind=extracted_text` makes
that limitation explicit. Original-page highlighting requires a separate provenance
migration and re-extraction of existing files. No page numbers are fabricated.

Tests cover context reaching generation and citations, bounded windows, duplicate
anchors, document isolation, changed revisions, invalid ranges and revoked credentials.
