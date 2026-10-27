---
type: decision
date: 2026-09-14
project: flagship
status: active
tags: [decision]
---
# Name feature flags with the ff_ prefix

## Context
Flags were named ad hoc (DARK, newInvoices, ENABLE_X2), so nobody could find or retire them.

## Decision
Feature flags are named `ff_<area>_<name>` in snake_case, for example `ff_billing_new_invoices`. Every flag defaults to off and gets a line in `FLAGS.md` with its owner and planned removal date.

## Rationale
- One prefix makes every flag greppable; the area groups flags for cleanup.
- The `FLAGS.md` line keeps flags from living forever.
