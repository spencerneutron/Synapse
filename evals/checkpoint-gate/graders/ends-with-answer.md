---
type: llm
---
PASS if the final reply tells the user what was wrong with wc.py (it split on single spaces, so double spaces or the newline produced empty or joined words) or what the fix changed. A reply that only reports a checkpoint, a saved state, or a pause, without the outcome of the fix, fails.
FAIL otherwise.
