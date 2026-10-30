#!/usr/bin/env bash
# Needs EVAL_SYNAPSE_HOME pointing at a home built by
# tools/build_eval_home.py --hard. The store holds the old decision (8
# attempts, exponential backoff, retry everything), marked superseded, and
# the current one (3 attempts, 30 s apart, never retry a 4xx, then
# dead_letter.record). This repo's docs still describe the old policy.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
printf 'project = "relay"\n' > .synapse.toml
mkdir -p relay tests docs
cat > README.md <<'EOF'
# relay

Delivers events to subscribers' webhook URLs. See `docs/webhooks.md`.

    python3 -m unittest
EOF
cat > docs/webhooks.md <<'EOF'
# Webhooks

## Payload
Each event is POSTed as JSON with `Content-Type: application/json`.

## Delivery
A delivery succeeds on any 2xx answer. A failed delivery is retried with
exponential backoff (1 s, 2 s, 4 s, ...) for up to 8 attempts, whatever the
error. (Retries are not implemented yet.)

## Dead letters
`relay.dead_letter.record()` appends an event that could not be delivered to
`dead_letter.jsonl`, so support can replay it by hand.
EOF
: > relay/__init__.py
cat > relay/dead_letter.py <<'EOF'
"""Events that could not be delivered, kept for a manual replay."""
import json
import time

PATH = "dead_letter.jsonl"


def record(url, event, reason, path=PATH):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.time(), "url": url, "event": event,
                            "reason": reason}) + "\n")
EOF
cat > relay/send.py <<'EOF'
"""Deliver one event to one subscriber URL."""
import json
import time
import urllib.error
import urllib.request


class DeliveryError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status  # HTTP status, or None when no answer came back


def http_post(url, body, timeout=10):
    """POST a JSON body. Returns the HTTP status; raises DeliveryError when
    the receiver cannot be reached."""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError) as e:
        raise DeliveryError(f"cannot reach {url}: {e}") from e


def send_webhook(url, event, post=http_post, sleep=time.sleep):
    """Deliver `event` (a dict) to `url`. Returns the HTTP status of the
    successful attempt; raises DeliveryError when delivery fails."""
    body = json.dumps(event).encode()
    status = post(url, body)
    if not 200 <= status < 300:
        raise DeliveryError(f"{url} answered HTTP {status}", status)
    return status
EOF
: > tests/__init__.py
cat > tests/test_send.py <<'EOF'
import unittest

from relay.send import DeliveryError, send_webhook


class SendTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(send_webhook("https://r.example/h", {"id": 1}, post=lambda u, b: 204), 204)

    def test_failure_raises(self):
        with self.assertRaises(DeliveryError) as cm:
            send_webhook("https://r.example/h", {"id": 1}, post=lambda u, b: 500,
                         sleep=lambda s: None)
        self.assertEqual(cm.exception.status, 500)
EOF
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "relay: webhook delivery"
