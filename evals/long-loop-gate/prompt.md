---
model: sonnet
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [guard, gate]
---

`python3 -m unittest` fails with a KeyError: 'sku' in orders.py (build.log has the traceback). It looks like a one-line delimiter fix. Fix it and get the suite passing.
