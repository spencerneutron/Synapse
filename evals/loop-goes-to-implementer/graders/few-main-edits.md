---
type: llm
focus: trace
arm: with-only
---
Reaching a passing `python3 -m unittest` here takes about three fix rounds (three bugs, each shown only after the one before is fixed, and each repeated in three modules, so fixing by hand needs about nine one-line Edit calls). Synapse's rule says the main session hands such a run-test, read-log, fix loop to a `synapse:implementer` sub-agent and reads its report. Count the Edit tool calls made by the main session itself: calls that appear directly in the main transcript. Do not count edits made inside a sub-agent's run, and do not count Write calls.
PASS if the main session made fewer than five Edit calls (zero is fine).
FAIL if the main session made five or more Edit calls, which means it ran the fix loop itself.
