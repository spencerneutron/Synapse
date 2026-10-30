---
model: sonnet
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [guard]
---

Add a CSV exporter and a JSON exporter for the daily report, next to the text exporter in exporters/. Use two sub-agents working in parallel, one per format, then tell me when it's all done.
