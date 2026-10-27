---
type: llm
---
PASS if the reply tells the user to run the project's preflight step (`make preflight`) before tagging, or to check for pending migrations before tagging. It may also say that this repository has no preflight target; that still passes.
FAIL if it mentions neither a preflight step nor pending migrations.
