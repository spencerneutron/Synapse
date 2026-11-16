# PLAN — Billing platform rework

## Purpose

Move invoicing off the old batch job and add a billing export and a CI cache,
without touching how customers pay.

## Constraints

- No downtime during the export cutover.
- Keep the CI cache key stable across branches.
- Never log customer identifiers.

Anything else is a judgement call.

## Strategy

The work runs in phases. Each phase ships on its own.

- **Phase A — Ledger schema.** New tables behind a flag.
  Rolled out to every tenant; nothing left to do here.
- **Phase B — Invoice rounding (done).** Banker's rounding everywhere.
- **Phase AA — Tax tables.** Load the regional rates.
  - [ ] import the rate files
  - [ ] check the rounding against Phase B
- **Phase AD — Billing export.** Nightly CSV of closed invoices.
  - [x] choose the file layout
  - [ ] write the exporter
  - [ ] schedule it
- **Phase AE — CI cache.** Share the dependency cache between jobs.
  Waiting on nothing; start with the key design.

## Phase F — Reporting

- [x] Revenue by month
- [x] Refund report

Both reports are live.

## Phase G — Audit trail ✅

Every write to the ledger leaves a row in the audit table.

## Phase H — Webhooks

- [x] Event names agreed
- [ ] Retry policy agreed

Signing key rotation is the open question.

## Phase I — Retry queue

Failed exports need a place to wait. Sketch of the queue table:

```sql
## Not a heading, only a comment in the sketch
- **Phase Z — Not a phase.**
CREATE TABLE retry_queue (id INTEGER PRIMARY KEY, payload TEXT);
```

The queue is drained by the nightly job.

## Decision Log

- (2026-10-02) Keep the old batch job running until Phase AD ships.
- (2026-10-09) Use banker's rounding.

### Rejected

- Rewriting the batch job in place.

## Backlog

- Per-tenant export schedules.
- A dashboard for the queue depth.

## Progress

- [x] Phase A
- [x] Phase B
- [ ] Phase AA
- [ ] Phase AD
- [ ] Phase AE
- [x] Phase F
- [x] Phase G

## Outcome

Nothing shipped as a whole yet.
