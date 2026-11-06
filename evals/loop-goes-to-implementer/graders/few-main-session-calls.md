---
type: llm
focus: trace
arm: with-only
---
Reaching a passing `python3 -m unittest` here takes about three fix rounds (three bugs, each shown only after the one before is fixed, and each repeated in three modules). Synapse's rule says the main session hands such a run-test, read-log, fix loop to a `synapse:implementer` sub-agent and reads its report; a Synapse hook reminds the main session at its fifth hands-on call in a row, so a dispatch may come right after that reminder. Count the hands-on calls the main session itself made to Bash, PowerShell, Edit, Write, and NotebookEdit: calls that appear directly in the main transcript. Do not count calls made inside a sub-agent's run, and do not count read-only tools (Read, Grep, Glob) or the Agent call itself.
PASS if either holds: (a) the main session made fewer than five such calls in all; or (b) the main session dispatched `synapse:implementer`, made at most six such calls before that Agent call, and at most two after it (verification).
FAIL otherwise: the main session ran the fix loop itself, or kept working past six calls before dispatching, or redid the work after the dispatch.
