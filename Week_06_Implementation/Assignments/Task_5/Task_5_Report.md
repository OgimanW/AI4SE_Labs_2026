# Task 5 – Solving the missing methods with the RAG pipeline

**Script:** `solver.py`  ·  **Run:** `python solver.py --tasks missing_code.json`
**Model:** `gpt-5-mini`  ·  **Retrieval:** top 5 chunks (bge-small store, tests included)
**Cost of the run:** 17.4 k input + 7.6 k output tokens for all 10 tasks.

## Pipeline (per task)

1. **Task text.** Each entry of `missing_code.json` (file, class, method,
   docstring) becomes the query `Class.method: <docstring>`.
2. **Retrieval.** `Matcher.match_text(query, n=5)` returns the 5 most similar
   chunks. Test chunks are allowed on purpose, because the tests specify the exact
   expected behaviour.
3. **Prompt.** The prompt contains the task, the current stub (its signature),
   the imports of the target file and the 5 retrieved chunks as Markdown blocks
   with file and line numbers. The system prompt asks for *only* the complete
   method in one code block, with the signature unchanged and following the
   repository's conventions.
4. **Write-back.** The method is located in the target file with `ast` and
   replaced by the returned code, re-indented to the class. The result must parse
   and must define the right method; otherwise the model gets one retry with the
   error. The originals are kept as `*.py.orig` (`--restore`).
5. **Unit tests.** `python -m unittest discover` runs before and after all tasks.
   The script saves a JSON run log, the full test log and `results/TEST_REPORT.md`.

## Results

| | tests | passed | failed | pass rate |
|---|---|---|---|---|
| before (10 stubs) | 481 | 429 | 52 | 89.2 % |
| **after RAG solver** | **481** | **471** | **10** | **97.9 %** |

All 10 methods were written on the first attempt (no syntax retries were needed).
**8 of 10 are fully correct**, and every test for them passes: `OrderStatus.is_terminal`,
`Warehouse.stock_report`, `OrderStateMachine.transition`, `OrderLog.by_status`,
`Customer.can_afford`, `Order.__len__`, `EventBus.__contains__`, `Money.__bool__`.
That fixed 42 of the 52 failing tests.

## The remaining 10 failures – two methods

**`BulkDiscountPricing.price` – 7 tests** (6 in `test_pricing`, 1 in `test_orders`).
The logic is right (sum the quantities, compare with the threshold, discount by
floor division), but the model wrote `(base_total * percent_off) // 100`.
`Money` defines `*` but not `//`, so every discounted case raises a `TypeError`.
The correct pattern, `Money(total.cents * x // 100)`, is used two classes above
in `FlatPricing.price`. **Retrieval missed it:** the top 5 were the
`BulkDiscountPricing` class itself and four test chunks. Neither `FlatPricing`
nor the `Money` operators were among them.

**`InventoryLedger.__contains__` – 3 tests.** The docstring says *"positive
on-hand stock"*, but the tests expect something else:

* `True` for a SKU that was fully committed (0 on hand, but the key is still in
  `_on_hand`);
* `False` instead of an exception for non-string or malformed SKUs.

The model followed the docstring and let `normalize_sku` raise. The test chunk
that defines this behaviour (`test_inventory.py` lines 212–232) **was not
retrieved**. The 5 chunks included other ledger tests, but not the `__contains__` ones.

## Takeaways

* RAG with only 5 chunks of ~250 tokens (~1.3 k tokens of context per task) was
  enough for a small model to implement 8 of 10 methods correctly.
* Both failures come from **retrieval, not from the model.** In each case the
  chunk with the decisive information (a code pattern or a spec test) ranked just
  outside the top 5. Possible improvements:
  * always add the chunks of the target class's direct dependencies
    (here `Money`);
  * retrieve tests separately with a query on the method name
    (`__contains__`);
  * add a feedback loop that runs the relevant tests and sends the failures back
    to the model.
* When a docstring and the tests disagree (`__contains__`), the tests are the
  real specification. The prompt already says so, but the model can only follow
  tests it was actually shown.
