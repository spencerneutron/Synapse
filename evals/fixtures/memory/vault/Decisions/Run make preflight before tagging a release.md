---
type: decision
date: 2026-08-02
project: flagship
status: active
tags: [decision]
---
# Run make preflight before tagging a release

## Context
Two releases shipped with an unapplied migration and a missing changelog entry.

## Decision
Before tagging any release, run `make preflight`. It checks pending migrations, the changelog entry, and that `VERSION` matches the tag. Tag only after it passes.

## Rationale
- Both failures were caught by nothing until production.
