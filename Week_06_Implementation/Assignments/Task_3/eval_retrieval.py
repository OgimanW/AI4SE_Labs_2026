#!/usr/bin/env python3
"""
eval_retrieval.py - sanity-check retrieval quality on hand-written coding
tasks. A query counts as a hit if a chunk containing the expected symbol is
returned among the top-k (source code only, tests excluded).

Usage:  python eval_retrieval.py [--store vector_store]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedder import DEFAULT_STORE, VectorStore  # noqa: E402

# (task description, expected qualified symbol)
TASKS = [
    ("Customers should not be able to spend more than their credit limit", "Customer.can_afford"),
    ("Add a 10% discount when someone buys more than a threshold quantity", "BulkDiscountPricing.price"),
    ("Tax is computed wrongly, it should be rounded half up in basis points", "FlatPricing.price"),
    ("Prevent shipping an order that was already cancelled", "OrderStateMachine.transition"),
    ("Allow removing a line item from an order before it is placed", "Order.add_item"),
    ("Reserving stock should fail if there is not enough quantity available", "InventoryLedger.reserve"),
    ("Release reserved stock automatically when the reservation context exits with an error", "ReservationContext"),
    ("Format an amount of cents as a dollar string like $12.34", "format_cents"),
    ("SKU codes must be normalised to upper case without spaces", "normalize_sku"),
    ("Event handlers should be able to unsubscribe from the event bus", "EventBus.unsubscribe"),
    ("Log every call of a decorated function with its arguments", "AuditTrail"),
    ("Parse a product category from a free-text label, case insensitive", "Category.from_label"),
    ("Creating a product from a dictionary should validate the price", "Product.from_dict"),
    ("The in-memory repository should raise when adding a duplicate id", "InMemoryRepository.add"),
    ("Simulation summary should include average order value", "SimulationReport.summary"),
    ("Make the random simulation reproducible with a seed", "Simulation"),
    ("Out of stock error message should contain requested and available quantity", "OutOfStockError"),
    ("Money subtraction must not allow negative results", "Money.__sub__"),
    ("Order builder should merge repeated SKUs into one line item", "OrderBuilder.add"),
    ("Warehouse stock report should list only SKUs with non-zero quantity", "Warehouse.stock_report"),
]


def evaluate(store: VectorStore, k_values=(1, 3, 5)) -> dict:
    hits = {k: 0 for k in k_values}
    rr = 0.0
    misses = []
    for query, sym in TASKS:
        res = store.search(query, k=max(k_values), include_tests=False)
        rank = next((i + 1 for i, r in enumerate(res)
                     if any(s == sym or s.startswith(sym + ".") for s in r["symbols"])),
                    None)
        if rank:
            rr += 1 / rank
            for k in k_values:
                hits[k] += rank <= k
        else:
            misses.append((query, sym, res[0]["symbols"][:3]))
    n = len(TASKS)
    return {"n": n, **{f"hit@{k}": hits[k] / n for k in k_values},
            "mrr@5": rr / n, "misses": misses}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=DEFAULT_STORE)
    args = ap.parse_args()
    store = VectorStore.load(args.store)
    r = evaluate(store)
    print(f"backend={store.backend.name} [{store.backend.model_name}]  n={r['n']}")
    print("  ".join(f"{k}={v:.2f}" for k, v in r.items() if k not in ("n", "misses")))
    for q, sym, got in r["misses"]:
        print(f"  MISS: {q!r}  expected {sym}, top-1 {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
