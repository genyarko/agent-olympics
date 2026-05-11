# Evidence Context Scaling (Future Refactor)

## Current Implementation
Currently, the `verifier.py` agent injects the *entire* `facts` and `research_findings` blocks into the prompt for *every single claim* during the semantic grounding phase.

```python
evidence = f"FACTS:\n{facts}\n\nRESEARCH FINDINGS:\n{research}"
```

## Problem
While Gemini 2.5 Flash handles large contexts exceptionally well and is fast, this approach introduces redundant token usage. If the research findings are 10,000 tokens and there are 15 claims, we are sending 150,000 tokens to Gemini simultaneously. For a hackathon vertical, this is perfectly acceptable, but it is not scalable or cost-effective for a production system processing numerous large documents.

## Proposed Solution (RAG Approach)
For a production system, we should use a Retrieval-Augmented Generation (RAG) approach to fetch only the relevant evidence chunks per claim.

1.  **Chunking:** Break down the `facts` and `research_findings` into smaller, semantically meaningful chunks (e.g., by paragraph or specific finding).
2.  **Embedding:** Generate vector embeddings for each chunk.
3.  **Retrieval:** For each extracted `Claim`, generate its embedding and retrieve the top-K most similar chunks from the evidence pool.
4.  **Targeted Grounding:** Pass only the retrieved top-K chunks as `evidence` to the `semantic_grounding` prompt.

This will significantly reduce token consumption and potentially improve grounding accuracy by focusing the LLM on the most relevant text.
