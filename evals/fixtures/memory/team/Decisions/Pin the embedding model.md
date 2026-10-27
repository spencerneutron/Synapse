---
type: decision
date: 2026-09-02
project: flagship
tags: [decision]
origin: acme
author: sam
shared_at: "2026-09-02T10:00:00+00:00"
---
# Pin the embedding model

## Context
Recall quality dropped when vectors from two embedding models ended up side by side.

## Decision
Pin one embedding model per index. Never mix two models in one index, not even during a migration: build the new index beside the old one and switch over at once.
