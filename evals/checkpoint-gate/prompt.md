---
model: sonnet
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [gate]
---

`python3 wc.py notes.txt` reports 9 words but the file has 8. Fix wc.py and tell me what was wrong.
