---
type: regex
target: last_message
pattern: "(^#{1,6}[ \\t].*$[\\s\\S]*?){4}"
flags: m
match: not_contains
---
