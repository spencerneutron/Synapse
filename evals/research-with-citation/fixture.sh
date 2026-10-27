#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p docs src
cat > docs/config.md <<'MD'
# Configuration

## Retries

Request retries are set in `service.toml` under `[retry]`: `max_attempts`
(default 3) and `backoff_ms` (default 250).
MD
cat > docs/logging.md <<'MD'
# Logging

Log shipping retries forever and is not configurable.
MD
printf '# retries are handled by config\n' > src/client.py
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "docs"
