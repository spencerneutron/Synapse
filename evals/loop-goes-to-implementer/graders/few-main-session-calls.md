---
type: llm
focus: trace
arm: with-only
---
Reaching a passing `python3 -m unittest` here takes about three fix rounds (three bugs, each shown only after the one before is fixed, and each repeated in three modules). Synapse's rule says the main session hands such a run-test, read-log, fix loop to a `synapse:implementer` sub-agent and reads its report. With a dispatch, the main session typically runs the test once, maybe reads the log, dispatches, and re-runs once to verify: about 2-3 state-changing or run calls. Doing the three rounds itself takes at least one run and one write per round, so six or more. Count the calls the main session itself made to Bash, PowerShell, Edit, Write, and NotebookEdit: calls that appear directly in the main transcript. Do not count calls made inside a sub-agent's run, and do not count read-only tools (Read, Grep, Glob).
PASS if the main session made fewer than five such calls.
FAIL if the main session made five or more such calls, which means it ran the fix loop itself.
