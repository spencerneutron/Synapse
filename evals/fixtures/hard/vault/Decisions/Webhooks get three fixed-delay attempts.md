---
type: decision
date: 2026-09-30
project: relay
status: active
tags: [decision]
---
# Webhooks get three fixed-delay attempts

## Decision
Webhook delivery makes at most 3 attempts, 30 s apart (fixed, no backoff), and never retries a 4xx; after the last failure, call `dead_letter.record()`. Replaces the 8-attempt backoff policy.

## Context
Two large receivers rate-limited and then blocked us in September: eight
attempts with backoff, retried even on 400 and 410 answers, looked like an
attack. Their ops teams asked for few, evenly spaced attempts and no retries
on client errors.

## Rationale
- A 4xx means the request itself is wrong; repeating it cannot succeed.
- The dead-letter file lets support replay an event by hand once the
  receiver is fixed.
