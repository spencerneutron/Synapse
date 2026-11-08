---
type: regex
target: { source: file, path: .claude-work/current/EXECUTION.md }
pattern: '^##[ \t]+Resume\b.*\n(?:[ \t]*\n)*[ \t]*[^#\s]'
flags: m
---
