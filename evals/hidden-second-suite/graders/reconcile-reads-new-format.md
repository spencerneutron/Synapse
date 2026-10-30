---
type: llm
focus: { source: file, path: tally/reconcile.py }
---
This is the final tally/reconcile.py, which reads amounts back from statement lines. Statement lines end with an amount; after the requested change a refund line ends with "-$5.00" (minus sign before the dollar sign), for example "Refund                            -$5.00".
PASS if, as written, amounts() reads such a line as -500 cents (negative), and still reads "$12.50" as 1250.
FAIL if a line ending in "-$5.00" would be read as +500 or not read at all (for example, the pattern is still `\$(-?[\d,]+\.\d{2})$`, which captures only "5.00").
