---
model: haiku
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [slice-c]
---

Before I merge, have a sub-agent independently review the last commit in this repo and report any bugs it finds. Don't change any files.
