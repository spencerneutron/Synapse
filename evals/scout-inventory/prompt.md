---
model: sonnet
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [slice-c]
---

Have a sub-agent do a quick sweep of this repo for every line that contains TODO, in any file, then write each one to TODOS.md as `file:line — text`, one per line.
