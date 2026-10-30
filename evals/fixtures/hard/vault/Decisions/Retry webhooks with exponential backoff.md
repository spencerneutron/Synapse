---
type: decision
date: 2026-05-04
project: relay
status: active
tags: [decision]
---
# Retry webhooks with exponential backoff

## Decision
Webhook delivery retries every failed attempt with exponential backoff (1 s, 2 s, 4 s, and so on), up to 8 attempts, whatever the error.

## Rationale
- Receivers are often briefly down during deploys; backoff rides that out.
