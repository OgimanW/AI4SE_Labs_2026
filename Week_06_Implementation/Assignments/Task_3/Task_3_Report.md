# Task 3 – Embeddings and retrieval

**Files:** `embedder.py` (chunk → embedding, storage, search), `vector_store/`
(the stored chunk–embedding pairs), `eval_retrieval.py` (quality check), this report.

```
python embedder.py build                    # embed chunks.json -> vector_store/
python embedder.py search "add VIP discount" -k 5 --no-tests --show
python eval_retrieval.py                    # Hit@k / MRR on 20 test tasks
```

## 1. Embedding mechanism

The script has **two backends** behind one interface (`fit`, `embed_documents`,
`embed_query`):

| | `bge` (default) | `lsa` (offline fallback) |
|---|---|---|
| Method | pre-trained transformer **BAAI/bge-small-en-v1.5** | TF-IDF on code-aware tokens + truncated SVD (Latent Semantic Analysis) |
| Runtime | `fastembed` (ONNX, CPU, no PyTorch) | numpy + scikit-learn |
| Dimension | 384 | 128 |
| Max input | 512 tokens | unlimited |
| Needs | a one-time model download (~130 MB) | nothing |

**Why bge-small as the main choice.** It is a small, fast and widely used
retrieval model that is strong on the MTEB retrieval benchmarks and runs on any
laptop CPU. Its 512-token window matches the hard chunk limit from Task 2, so no
chunk gets truncated. It is also an *asymmetric* retrieval model: queries get the
instruction prefix *"Represent this sentence for searching relevant passages:"*,
while documents don't. That fits our use case, where a natural-language task
description is used to find code. Larger code-specific models (e.g. jina-code,
CodeT5+) would be overkill for a 40 k-token repository.

**Why there is a fallback.** In the environment where the store was built, the
network blocked Hugging Face, so the model could not be downloaded. Instead of
making the pipeline depend on one external download, `embedder.py` falls back
automatically to LSA. LSA is the classic way to get dense vectors from text:
TF-IDF builds a sparse term–chunk matrix, and SVD compresses it into 128 latent
dimensions. Terms that occur together (e.g. *reserve*, *stock*, *ledger*) end up
close in this space, so a query can match a chunk without using exactly the same
words. 128 dimensions is close to the maximum here, since SVD rank is limited by
the number of chunks (175).

> **The final `vector_store/` was built with the `bge` backend** (384-dim) on my
> own machine, where the model could be downloaded. The LSA store was built and
> evaluated first, in an environment without access to Hugging Face. Both
> backends are kept, and the pipeline is the same for either.

## 2. What is embedded

For each chunk the embedded text is:

```
# Symbols: Customer, Customer.__init__, ..., Customer.can_afford, Customer.charge
# File: playground/playground/models.py
# Module: Core domain models: money, products, line items, and customers.
<source code of the chunk, including docstrings>
```

* **Code with docstrings, not only signatures.** The docstrings are the most
  "natural-language" part of the code, which is what task descriptions look like.
  The bodies carry the identifiers.
* **Context header + symbol names.** A method group still knows its file and
  class, and exact names (`can_afford`) become searchable terms.
* **Code-aware tokenisation (LSA).** `OrderBuilder.add_item` is indexed as
  `orderbuilder, order, builder, add_item, add, item`, so both the exact
  identifier and the plain-English words match. Python keywords and `self` are
  dropped as stop-words.

## 3. Storage and retrieval

`vector_store/` holds:

* `vectors.npy`: float32 matrix *N × d*, with rows L2-normalised.
* `index.json`: the backend and model, the dimension, a SHA-1 of the
  `chunks.json` it was built from (to detect stale stores), and metadata for every
  row (`id`, file, lines, symbols, `is_test`). The full code stays in `chunks.json`
  and is looked up by `id`, so it isn't duplicated.
* `lsa.pkl`: the fitted TF-IDF vocabulary and SVD, needed to project queries
  into the same space (LSA only).

**Retrieval is exact cosine similarity.** Because the vectors are normalised,
cosine is one matrix–vector product, followed by a top-k selection
(`argpartition`). For 175 × 128 this takes microseconds, and it stays fast up to
~10⁵ chunks. An approximate-nearest-neighbour index (FAISS, HNSW) or a vector
database (Chroma, Qdrant) only pays off far beyond that, and it would add a
dependency and trade away exactness. `search()` also supports filters the agent
will need: `include_tests=False` and a `file_prefix`.

## 4. Does it work?

`eval_retrieval.py` runs 20 hand-written coding tasks phrased the way an issue
would be (e.g. *"Customers should not be able to spend more than their credit
limit"* → `Customer.can_afford`). It searches source chunks only and counts a hit
if the expected symbol is in a returned chunk.

| Variant | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
|---|---|---|---|---|
| **bge-small-en-v1.5, header + symbols (final store)** | **0.85** | **1.00** | **1.00** | **0.92** |
| TF-IDF sparse, plain word tokens | 0.60 | 0.90 | 0.95 | 0.75 |
| TF-IDF sparse, code-aware tokens | 0.60 | 1.00 | 1.00 | 0.78 |
| LSA 32 dims | 0.60 | 0.95 | 1.00 | 0.77 |
| LSA 64 dims | 0.65 | 0.90 | 1.00 | 0.80 |
| LSA 128 dims, header + symbols (offline fallback) | 0.70 | 1.00 | 1.00 | 0.83 |
| LSA 128 dims, raw code only | 0.65 | 1.00 | 1.00 | 0.81 |

With both backends, the right chunk is always in the top 3, so top-k = 3–5 is a
sensible default for the agent. The pre-trained bge model mainly improves
**ranking**: it puts the expected chunk first in 17 of 20 tasks, while LSA does so
in 14. bge understands paraphrases that never appear in the code. Within LSA,
code-aware tokens, the SVD compression and the context header each add a little.

**Limitations.** The test set is small, and I wrote it while knowing the code, so
the numbers show that the pipeline works rather than give a benchmark. LSA only
learns from this one repository, so it can't link synonyms that never occur in
the code (e.g. *"refund"* when the code says *"release"*). That is exactly where
bge does better, which matches the higher Hit@1 above.
