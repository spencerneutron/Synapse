---
type: decision
date: 2026-10-05
project: flagship
tags: [decision]
---
# Keep both embedding models during a migration

## Context
A full re-embed of the flagship store takes most of a day, and recall must keep working meanwhile.

## Decision
During an embedding model migration, keep the old and new vectors in one index for up to a week, tag each chunk with its model, and query each model's vectors separately; then delete the old ones.
