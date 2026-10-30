---
model: sonnet
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [hard]
---

Orders go missing in the warehouse after some nightly exports, and the export log shows nothing wrong: every batch reported as sent. Can you track it down and fix it?
