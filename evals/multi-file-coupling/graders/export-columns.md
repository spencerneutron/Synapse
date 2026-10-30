---
type: regex
target: { source: file, path: config/export.ini }
flags: m
pattern: '^columns\s*=(?=.*\btotal_cents\b)(?!.*\btotal\s*(,|$))'
---
