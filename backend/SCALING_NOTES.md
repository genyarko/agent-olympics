# Evidence Context Scaling (Future Refactor)

## Current Implementation
`agents/verifier.py` runs a small pipeline over the final Board Brief:

1. **Extraction** — the brief is broken into atomic claims.
2. **Grounding** — each claim is first matched against sentence-level source
   passages with `rapidfuzz`. Anything that isn't an obvious textual match is
   sent — *as a single batched call* — to the LLM for a semantic verdict, along
   with the source corpus (`facts` + `research_findings` + raw document/url/image
   inputs).
3. **Consistency** — one batched LLM call checks every claim for internal
   contradictions and contradictions against the source corpus.
4. **Aggregation** — a weighted per-claim Integrity Score
   (`0.50·grounding + 0.35·consistency + 0.15·type_modifier`) and an overall
   score with a hallucination penalty; claims are classified
   VERIFIED / PLAUSIBLE / FLAGGED / HALLUCINATION.

The corpus is truncated at `MAX_CORPUS_CHARS` (currently 40k chars) so the
grounding/consistency prompts stay bounded.

## Problem
The grounding and consistency passes each send the *entire* truncated corpus in
one prompt. That's fine and fast for a hackathon-scale workload, but for a
production system processing many large documents it is wasteful and ultimately
limited by the truncation cap — long source material gets cut off rather than
intelligently retrieved.

## Proposed Solution (RAG approach)
1. **Chunking** — split `facts` and `research_findings` into smaller,
   semantically meaningful chunks (by finding / paragraph).
2. **Embedding** — embed each chunk.
3. **Retrieval** — for each extracted claim, embed the claim and retrieve the
   top-K most similar chunks.
4. **Targeted grounding** — pass only those top-K chunks to the grounding /
   consistency prompts instead of the whole corpus.

This removes the truncation ceiling, cuts token usage, and tends to improve
grounding accuracy by focusing the model on the most relevant text.
