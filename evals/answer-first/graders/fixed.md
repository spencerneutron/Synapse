---
type: llm
focus: { source: file, path: cart.py }
---
PASS if total() in this file returns 0 for an empty list and still returns the sum of price * qty for a non-empty list.
FAIL otherwise.
