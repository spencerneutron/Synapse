#!/usr/bin/env bash
# long-loop-goes-to-implementer's fixture plus a project .synapse.toml that
# drops the gate's context threshold to 0: eval sessions stay far below the
# default (half of a 150k-300k window), so without it the 2.7.0 PreToolUse
# gate would never fire here. The 2.6.1 nudge ignores the file, so the same
# case run against 2.6.1 measures the nudge alone. The prompt frames the job as
# a one-line fix, so the main session starts hands-on (the pattern measured in
# real sessions); with the original prompt Sonnet dispatched up front in both
# 2.6.1 and 2.7.0 and the gate never fired.
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../long-loop-goes-to-implementer/fixture.sh"
[ -f "$src" ] || { echo "fixture: $src not found" >&2; exit 1; }
bash "$src"
cat > .synapse.toml <<'TOML'
[gate]
min_context = 0
TOML
