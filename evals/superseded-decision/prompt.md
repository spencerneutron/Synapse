---
model: sonnet
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [hard]
---

Receivers are sometimes briefly down and we lose webhook deliveries. Add retries to send_webhook.
