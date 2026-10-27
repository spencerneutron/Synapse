---
type: llm
---
PASS if the reply says request retries are configured in service.toml under [retry], with max_attempts defaulting to 3 and backoff_ms defaulting to 250.
FAIL if either default is wrong or missing.
