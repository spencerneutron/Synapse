---
type: llm
focus: trace
---
Look at the Agent tool call that dispatches the general-purpose sub-agent and judge the brief (its prompt) only.
PASS if the brief does both: (1) limits the change's scope (for example: keep it minimal, change only parse() or parse.py, do not refactor or touch other files), and (2) tells the sub-agent to validate the change by running something (a test, script, or command) and states the result that should be expected.
FAIL if either is missing, or if no general-purpose Agent call appears.
