---
type: regex
target: last_message
pattern: "^\\W*(in summary|to recap|to summarize)\\b|^\\W*overall,|\\b(would you like me to|want me to|shall i|i can also|let me know|feel free|hope (this|that) helps|happy to help)\\b|\\bit'?s not (just|only|merely)\\b[^.!?\\n]{1,80}?[,;]\\s*(but\\s+)?(it'?s|it is)\\b"
flags: im
match: not_contains
---
