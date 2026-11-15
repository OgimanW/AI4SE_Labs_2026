# Task 4 – Matching a task embedding to the stored chunks

**File:** `matcher.py` (uses the store and the backend from `embedder.py`, Task 3)

```
python matcher.py "Customers must not exceed their credit limit" -n 5 --no-tests --show
```

```python
from matcher import Matcher
m = Matcher()                                # loads vector_store/
vec = m.embed_task("Add a VIP discount")     # input task -> embedding
hits = m.match(vec, n=5, include_tests=False)  # n most relevant chunks
context = "\n\n".join(h.as_prompt() for h in hits)   # goes into the LLM prompt
```

## How one match works

1. **The input is an embedding.** `match(query_vec, n)` takes a vector, so any
   source of embeddings can be used. `match_text()` is a convenience wrapper: it
   embeds the task with **the same backend as the store** (bge with its query
   prefix, or LSA). Vectors from different models live in different spaces, so
   the matcher checks the dimension and refuses a mismatched query.
2. **Similarity = cosine.** Both bge and LSA vectors carry their meaning in the
   *direction*, not the length. All stored vectors are L2-normalised and the
   query is normalised too, so cosine is a single matrix–vector product
   (`vectors @ q`).
3. **Exact search, not approximate.** 175 chunks × 384 dims means scoring
   everything takes about 0.02 ms per query. An approximate-nearest-neighbour
   index (FAISS/HNSW) would add a dependency and could miss the true best chunk,
   with no speed gain at this size. Brute force stays practical up to roughly
   10⁵ chunks.
4. **Top-n selection with `argpartition`.** It finds the best candidates in O(N),
   and only those are sorted, not the whole score array.
5. **Filters the agent needs:** `include_tests=False` (look only at the code you
   will change), `file_prefix` (restrict to one package), and `min_score`
   (return fewer chunks rather than irrelevant ones, so the prompt doesn't fill up
   with noise).
6. **No duplicate context.** Window chunks of one long function overlap by
   design. A chunk whose line range overlaps a chunk already chosen from the same
   file is skipped, so the same lines never reach the prompt twice.
7. **Optional MMR (Maximal Marginal Relevance)**, enabled with `mmr_lambda`. It
   re-ranks a candidate pool (4 × n) to balance relevance against similarity to
   the chunks already picked. This helps broad tasks that touch several places,
   where plain ranking can return n near-identical chunks. **It is off by
   default.** On the 20 single-target test tasks it gives no gain at λ = 0.7, and
   at λ = 0.5 it drops Hit@3 from 1.00 to 0.85. Pure similarity ranking is the
   better default when a task points at one place in the code.

## Score range with bge (observed)

For the task *"Customers must not exceed their credit limit"*, the bge store
returned `Customer` (the correct chunk, with `can_afford`) at **0.724**. Ranks
2–5 (`Simulation.add_customer`, `OrderBuilder`, `Order`, `BulkDiscountPricing`)
scored **0.58–0.61**. Those chunks are only loosely related: they mention a
customer but contain no credit logic.

bge cosine scores are compressed. Even unrelated code from the same repository
lands around 0.5–0.6, because all chunks share vocabulary and style. So:

* an **absolute threshold** has to sit fairly high. Here `min_score=0.65` would
  keep only the correct chunk. It is also model-specific: the same number means
  something different for LSA, where unrelated chunks score around 0.2.
* the **gap from the top result** says more than the raw number: 0.72 vs. 0.61
  separates the relevant chunk clearly from the rest.

For that reason the default stays **n = 5 with no threshold**. A few loosely
related chunks cost little prompt space, while cutting off a needed chunk would
make the agent fail. When a tighter context is wanted, a threshold of about 0.6
for bge is a safe choice.

## Output

Each `Match` carries the rank, the cosine score, the chunk `id`, the file and
line range, the symbols, `is_test`, and the code itself. `as_prompt()` formats it
as a Markdown block with the path and lines. The agent in the next task can paste
that into the prompt, and the location tells it exactly which part of which file
to edit.

## Choosing n

The evaluation from Task 3 shows that the right chunk is always in the top 3
(Hit@3 = 1.00 for both bge and LSA). The default **n = 5** adds a safety margin
and room for related code, such as a caller or the matching tests. Five chunks of
about 250 tokens each are roughly 1.3 k tokens of context, cheap for any model.
