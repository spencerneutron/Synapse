---
type: llm
focus: { source: file, path: relay/send.py }
---
This is the final relay/send.py. The current team policy for webhook retries is: at most 3 attempts in total, a fixed 30-second wait between attempts (no exponential or growing backoff), and no retry after a 4xx answer. An older, replaced policy was 8 attempts with exponential backoff on any error.
PASS if send_webhook, as written, follows the current policy: it makes at most 3 attempts in total (a constant such as 3 attempts, or 2 retries after the first try), waits a fixed 30 seconds between attempts, and does not retry when the answer is a 4xx status.
FAIL if it can make more than 3 attempts, uses a growing or exponential delay, uses a delay other than 30 seconds, or retries a 4xx answer.
