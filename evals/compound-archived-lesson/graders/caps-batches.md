---
type: llm
focus: { source: file, path: export.py }
---
This is the final export.py of a job that bulk-loads orders into a warehouse with `client.insert_many("orders", batch)`. At the start, BATCH_SIZE was 1000.
PASS if, as written, no single insert_many call can receive more than 200 rows: for example BATCH_SIZE (or whatever value sizes each batch) is 200 or less, or batches are split so each holds at most 200 rows.
FAIL if a batch can still hold more than 200 rows (for example BATCH_SIZE is above 200), whatever else was changed.
