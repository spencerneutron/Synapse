---
model: sonnet
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [slice-c]
---

Use a general-purpose sub-agent (not one of the specialised ones) to change parse() in parse.py so it returns None for input that is not an integer instead of raising.
