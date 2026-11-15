# RAG solver – unit test results

Model: **gpt-5-mini**, retrieval: top 5 chunks, tokens: 17352 in / 7626 out

| | tests | passed | failed | pass rate |
|---|---|---|---|---|
| before (stubs) | 481 | 429 | 52 | 89.2 % |
| after RAG solver | 481 | 471 | 10 | 97.9 % |

## Tasks

| target | file | written | attempts |
|---|---|---|---|
| `OrderStatus.is_terminal` | playground/playground/enums.py | yes | 1 |
| `InventoryLedger.__contains__` | playground/playground/inventory.py | yes | 1 |
| `Warehouse.stock_report` | playground/playground/inventory.py | yes | 1 |
| `OrderStateMachine.transition` | playground/playground/orders.py | yes | 1 |
| `OrderLog.by_status` | playground/playground/orders.py | yes | 1 |
| `Customer.can_afford` | playground/playground/models.py | yes | 1 |
| `Order.__len__` | playground/playground/orders.py | yes | 1 |
| `BulkDiscountPricing.price` | playground/playground/pricing.py | yes | 1 |
| `EventBus.__contains__` | playground/playground/events.py | yes | 1 |
| `Money.__bool__` | playground/playground/models.py | yes | 1 |

## Tests still failing

- `test_inventory.InventoryLedgerContainsLenIterTests.test_contains_malformed_string_false`
- `test_inventory.InventoryLedgerContainsLenIterTests.test_contains_non_str_false`
- `test_inventory.InventoryLedgerContainsLenIterTests.test_contains_present_even_if_zero_on_hand_after_commit`
- `test_orders.OrderTotalTests.test_total_reflects_merged_quantities_for_bulk_discount`
- `test_pricing.BulkDiscountPriceTests.test_at_threshold_applies_discount`
- `test_pricing.BulkDiscountPriceTests.test_call_matches_price`
- `test_pricing.BulkDiscountPriceTests.test_discount_uses_floor_division`
- `test_pricing.BulkDiscountPriceTests.test_full_discount_yields_zero`
- `test_pricing.BulkDiscountPriceTests.test_quantity_summed_across_lines`
- `test_pricing.BulkDiscountPriceTests.test_wraps_base_with_tax`
