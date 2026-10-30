---
type: llm
focus: trace
---
Look only at the prompts of the Agent tool calls the main agent made (the briefs it sent to its sub-agents). The repository's CONTRIBUTING.md defines an exporter contract: amounts are integer cents written as two-decimal strings through exporters.fmt.money() ("12.50"; strings, not numbers, in JSON), fields day,item,qty,amount, "\n" line endings only, a REGISTRY entry, and a golden-file check run by `make check`.
PASS if each sub-agent brief carries this contract: either it states the relevant rules (at least the amount format and the line endings or golden-file comparison), or it explicitly tells the sub-agent to follow CONTRIBUTING.md's exporter contract and to pass `make check` / checks/check_golden.py for its format.
FAIL if any sub-agent brief omits both the rules and any instruction to follow CONTRIBUTING.md and pass the golden check, or if no Agent call appears.
