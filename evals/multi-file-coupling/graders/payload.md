---
type: regex
target: { source: file, path: shipq/payload.py }
flags: s
pattern: '^(?=.*["'']total_cents["'']\s*:)(?!.*["'']total["'']\s*:)'
---
