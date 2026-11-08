---
type: llm
focus: trace
arm: with-only
---
Reaching a passing `python3 -m unittest` here takes ten serial fix rounds: the pipeline stops at its first error and writes only that traceback to build.log, so each bug shows only after the one before it is fixed. Done by hand, this is a run-test, read-log, fix loop of about twenty hands-on calls. Synapse's rule says the main session hands such a loop to a `synapse:implementer` sub-agent and reads its report; in this case a Synapse PreToolUse gate denies the main session's next hands-on call once it has made five in a row, so a dispatch should come right after that denial. Count the hands-on calls the main session itself made to Bash, PowerShell, Edit, Write, and NotebookEdit: calls that appear directly in the main transcript, including a call the gate denied. Do not count calls made inside a sub-agent's run, and do not count read-only tools (Read, Grep, Glob) or the Agent call itself.
PASS if the main session made at most seven such calls in all (five, the denied one, a dispatch of `synapse:implementer`, and one verification call).
FAIL if it made more than seven: the main session ran the fix loop itself instead of dispatching, or redid the work after the dispatch.
