---
type: llm
focus: { source: file, path: shipq/formatters.py }
---
This is the final shipq/formatters.py. format_field(key, value) formats one payload field. The payload now carries `total_cents` (an int, 1250 for $12.50) instead of `total` (a float in dollars).
PASS if, as written, format_field("total_cents", 1250) returns "$12.50" (for example through a fmt_total_cents function that divides by 100).
FAIL if format_field("total_cents", 1250) would return anything else, such as "1250" (no matching formatter, so the str() fallback applies) or "$1,250.00".
