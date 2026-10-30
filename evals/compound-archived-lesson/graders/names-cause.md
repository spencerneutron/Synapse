---
type: llm
---
The real cause of the missing orders: the warehouse's bulk endpoint silently drops any batch of more than 200 rows (it answers success and stores nothing), and the job sent batches of 1000.
PASS if the reply names that cause: batches over the warehouse's 200-row limit being dropped without an error, with the fix of capping batches at 200 rows or fewer. It may also mention other changes, such as the swallowed timeout.
FAIL if the reply gives a different cause as the explanation (for example only the swallowed WarehouseTimeout, pagination, or retries), or does not identify the batch-size limit.
