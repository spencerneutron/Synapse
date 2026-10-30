---
type: regex
target: { source: file, path: templates/invoice.txt }
flags: s
pattern: '^(?=.*\{\{total_cents\}\})(?!.*\{\{total\}\})'
---
