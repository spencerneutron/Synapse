#!/usr/bin/env bash
# long-loop-goes-to-implementer's fixture plus a project .synapse.toml that
# drops the gate's context threshold to 0: eval sessions stay far below the
# default (half of a 150k-300k window), so without it the 2.7.0 PreToolUse
# gate would never fire here. The 2.6.1 nudge ignores the file, so the same
# case run against 2.6.1 measures the nudge alone.
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../long-loop-goes-to-implementer/fixture.sh"
[ -f "$src" ] || { echo "fixture: $src not found" >&2; exit 1; }
bash "$src"
cat > .synapse.toml <<'TOML'
[gate]
min_context = 0
TOML
