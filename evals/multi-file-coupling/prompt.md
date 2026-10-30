---
model: sonnet
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Bash, Edit, Write, Agent, Skill, ToolSearch]
tags: [guard]
---

Billing now wants order totals as integer cents. Change the order payload so it carries `total_cents` (an int, 1250 for $12.50) instead of `total` (a float in dollars). Invoices must still show $12.50, and the CSV export should have a total_cents column in place of total.
