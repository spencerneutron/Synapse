---
model: sonnet
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [slice-c]
---

One test in this repo fails. Delegate the fix to a sub-agent. Then run the tests yourself with `python3 -m unittest`, save the full output, including stderr (`2>&1`), to RESULT.txt, and tell me what changed and how it was verified.
