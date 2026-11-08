---
model: sonnet
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [core]
---

slugify("  Hello,   World! ") in text.py returns "--hello----world--" instead of "hello-world". Fix it, explain what was going on, and give me an overview of the edge cases slugify still gets wrong after your fix.
