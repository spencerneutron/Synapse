---
type: llm
focus: trace
---
The repository has two suites: unit tests (`python3 -m unittest`, or `make test`) and integration checks in integration/ that only `make check` (or `python3 -m unittest discover -s integration -p "check_*.py"`) runs. Find the agent's last edit to any file under tally/, then look at the commands the agent ran after it.
PASS if, after that last edit, the agent ran the integration checks (via `make check` or the discover command on integration/) and that run's output shows them passing (OK, no FAILED or ERROR).
FAIL if the agent never ran the integration checks after its last edit to tally/, or if the last such run shows a failure or error.
