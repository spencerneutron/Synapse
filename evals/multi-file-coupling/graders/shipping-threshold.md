---
type: llm
focus: { source: file, path: shipq/shipping.py }
---
This is the final shipq/shipping.py. Payloads now carry `total_cents` (an int: 5000 means $50.00) instead of `total` (dollars). Shipping is a flat fee, free once the order reaches $100. The question is only whether the free-shipping threshold still means $100; the unit the fee is returned in (dollars or cents) does not matter.
PASS if, as written, shipping_fee({"total_cents": 5000}) returns a non-zero fee and shipping_fee({"total_cents": 15000}) returns 0 (the threshold is compared in cents, for example 10000, or the cents are converted to dollars first).
FAIL if shipping_fee({"total_cents": 5000}) would return 0 (for example it compares cents with 100), if it still reads payload["total"], or if either call would raise.
