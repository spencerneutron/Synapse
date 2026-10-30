---
type: regex
target: { source: file, path: shipq/checks.py }
flags: s
pattern: '^(?=.*["'']total_cents["'']\s*:)(?!.*["'']total["'']\s*:)'
---
