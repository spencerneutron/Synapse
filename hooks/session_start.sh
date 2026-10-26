#!/usr/bin/env bash
# Print one of Synapse's always-on rule sets as SessionStart additionalContext.
#   core      instructions/core.md
#   platform  the profile for this OS (macOS or Windows Git Bash); none elsewhere
# The JSON is prebuilt by tools/build_context.py, so this needs only bash.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/context"
case "${1:-core}" in
    core) f="$DIR/core.json" ;;
    platform)
        case "$(uname -s 2>/dev/null)" in
            Darwin) f="$DIR/platform-macos.json" ;;
            MINGW*|MSYS*|CYGWIN*) f="$DIR/platform-windows.json" ;;
            *) exit 0 ;;
        esac ;;
    *) exit 0 ;;
esac
[ -f "$f" ] && cat "$f"
exit 0
