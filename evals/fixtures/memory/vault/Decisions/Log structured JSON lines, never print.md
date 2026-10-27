---
type: decision
date: 2026-07-21
project: flagship
status: active
tags: [decision]
---
# Log structured JSON lines, never print

## Decision
Services log one JSON object per line through the `log` helper; `print()` is not used for diagnostics.

## Rationale
- The log pipeline parses JSON lines; printed text is dropped.
