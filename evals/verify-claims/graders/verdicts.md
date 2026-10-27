---
type: llm
focus: { source: file, path: VERDICTS.md }
---
PASS if claim 2 (parse_int("abc") raises ValueError) is marked FALSE, and claims 1 and 3 are marked TRUE.
FAIL otherwise, or if the file is missing.
