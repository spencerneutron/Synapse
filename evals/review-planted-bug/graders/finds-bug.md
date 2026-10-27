---
type: llm
---
PASS if the reply says the latest commit introduced an off-by-one in moving_average's loop range: it now stops one window early and drops the final window, and the range should be len(values) - window + 1.
FAIL if the reply does not identify this bug, or says the change is fine.
