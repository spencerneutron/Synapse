---
type: regex
target: { source: file, path: web/invoice.js }
flags: s
pattern: '^(?=.*\bp\.totalCents\b)(?!.*\bp\.total\b)(?!.*total_cents)'
---
