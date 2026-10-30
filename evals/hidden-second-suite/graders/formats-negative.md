---
type: llm
focus: { source: file, path: tally/money.py }
---
This is the final tally/money.py. format_amount takes integer cents.
PASS if, as written, format_amount(-500) returns exactly "-$5.00", format_amount(-123456) returns "-$1,234.56", and positive amounts are unchanged (format_amount(1250) returns "$12.50").
FAIL if any of these is not what the code returns (for example it still returns "$-5.00").
