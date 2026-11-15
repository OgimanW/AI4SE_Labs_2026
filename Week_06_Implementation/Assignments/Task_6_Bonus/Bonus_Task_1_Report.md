# Bonus – An ideal pipeline for repository-aware code generation

## 1. What our experiment showed

The embedding pipeline from Tasks 2–5 fixed 8 of 10 methods (429 → 471 of 481
tests). Both failures had the same cause: **the information that decided the
answer was in the repository, but not in the top 5 chunks.**

* `BulkDiscountPricing.price` needed the pattern `Money(total.cents * x // 100)`.
  It sits **in the same file**, in `FlatPricing.price`, a few lines above the
  target.
* `InventoryLedger.__contains__` needed the tests that define its (unusual)
  behaviour. They are **in the test file of the same module**, `test_inventory.py`.

Neither chunk was semantically close to the query, but both are *structurally*
obvious neighbours of the target. A developer would open them without searching
at all. This leads to the main conclusion:

> For code, **structure is a stronger signal than semantic similarity.** Embedding
> search is useful for finding where to start when the location is unknown. It is
> a poor way to collect the context for a location you already know.

## 2. Answers to the three questions

**Is embedding matching the best strategy here? No, not on its own.** In our
setting the target (file, class, method) is given exactly, so retrieval doesn't
have to *find* anything. It only has to *collect* context around a known symbol.
Static analysis does that deterministically:

* the enclosing file;
* the types used in the signature and body (`Money`, `LineItem`);
* the base class (`PricingStrategy`);
* the callers (`Order.total`);
* the tests that reference the symbol.

Embeddings help with vague tasks ("make checkout respect credit limits") and in
huge repositories. They work best combined with lexical search (BM25/grep for
identifiers, which embeddings blur) and a reranker.

**Would a different number of chunks work better? Yes. The right unit is a token
budget, not a fixed k.** Five chunks were ~1.3 k tokens, about 1 % of what
current models accept. A fixed k is wrong in both directions: too little for a
method that touches several classes, and noise for a trivial `__len__`.
Retrieved items should be ranked, and then the context filled up to a budget
(e.g. 8–16 k tokens), with deduplication. For this repository, the whole project
is ~40 k tokens, so it fits into one prompt. For 10 tasks that would be ~0.4 M
input tokens, which costs cents with `gpt-5-mini`. **Below roughly 50–100 k
tokens, the simplest good pipeline is no retrieval at all:** just include the
whole repository.

**Should chunking be more sophisticated? Somewhat, but differently.** AST-aligned
chunks (Task 2) are already the right base. What is missing is *multiple views*
of the code at different levels of detail, instead of one flat list of chunks:

* **Symbol index** – every class, method and function with its exact location
  and code (what we have, but addressed by name, not only by vector).
* **Repository map / skeleton** – all files with class and method *signatures +
  first docstring line*, without bodies (~2–4 k tokens for this repo). It gives
  the model a global view ("`Money` has `__mul__` but no `__floordiv__`") at
  little cost.
* **Dependency graph** – imports, inheritance, calls, and *test → tested symbol*
  links (from imports and the names used in each test method).

## 3. Proposed pipeline

```
 task ──► 1 locate ──► 2 gather context ──► 3 rank & pack ──► 4 generate ──► 5 verify ─┐
            ▲                                                                  │       │
            └──────────────── 6 repair loop (test failures, errors) ◄──────────┘       ▼
                                                                                    apply
```

1. **Locate the target.** If file/class/method is given (our case), use it
   directly. Otherwise, run a hybrid search (BM25 + embeddings, merged with
   reciprocal-rank fusion) over the symbol index, then a cross-encoder or LLM
   reranker, to find candidate locations.
2. **Gather context, structure first.** From the graph collect:
   * the full target file;
   * the base class and the interfaces it implements;
   * definitions of the types used in the signature and body;
   * the callers of the target;
   * **the tests that exercise the target.**

   Add the repository skeleton. Use embedding search only to fill gaps
   (similar implementations elsewhere, conventions).
3. **Rank and pack to a budget.** Order by priority: target file > tests >
   direct dependencies > skeleton > semantic neighbours. Deduplicate overlapping
   spans. Show lower-priority items as signatures only when the budget is
   tight. Put the most important context at the start and end of the prompt.
4. **Generate as an edit.** Ask for the method, or a unified diff for edits
   across several files. Use the strongest model the budget allows. Optionally,
   let the model call tools (`read_file`, `grep_symbol`, `list_tests`) so it
   can fetch anything the packer missed. That is an agentic RAG loop, as opposed
   to one-shot retrieval.
5. **Verify cheaply, then precisely.**
   * the file parses (we already check this);
   * a linter or type checker (ruff/mypy) catches errors like `Money // int`
     before running any test;
   * the tests mapped to the target run first, then the full suite to catch
     regressions.
6. **Repair loop.** Send failing test names, assertion messages and tracebacks
   back to the model for 2–3 rounds at most, then keep the best version
   (most tests passing). Both of our failures would show up as clear error
   messages (`unsupported operand type(s) for //: 'Money' and 'int'`;
   `AssertionError: False is not true` in a named test), which a model can
   usually fix in one round.

**Safety and practical details.** Write to a copy or branch, never into the
only working tree (we used `.orig` backups). Run tests in a sandbox with a
timeout. Don't let the generated code edit the tests. Log every prompt and diff
for review.

## 4. Expected effect on our task

These are expectations, not measured results:

* **Step 2 alone** (target file + mapped tests) would have put both missing
  pieces into the prompt: `FlatPricing.price` and the `__contains__` tests.
* **Step 5** would catch the `Money // int` error even without them.
* **Step 6** gives a second chance for both.

With structure-first context plus a test-feedback loop, 10/10 (481/481) is a
realistic target for this repository. And it should take fewer model calls than
tuning the embedding retrieval would.

## 5. Summary

| Decision | Our assignment pipeline | Proposed |
|---|---|---|
| Retrieval | dense embeddings only | structure (AST + graph) first, hybrid BM25 + dense + rerank as fallback |
| Unit of context | top-5 chunks | token budget, priority-ordered; whole repo if it fits |
| Chunking | AST chunks | AST chunks + symbol index + repo skeleton + dependency/test graph |
| Generation | one shot | one shot + optional tool calls, output as an edit/diff |
| Verification | run tests once at the end | parse → lint/type check → mapped tests → full suite, with a repair loop |
