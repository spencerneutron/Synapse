---
model: sonnet
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [slice-c]
---

Use a sub-agent to check each claim in CLAIMS.md against the code and tests in this repo, then write the verdicts to VERDICTS.md, one line per claim number: TRUE or FALSE and why. Don't change the code.
