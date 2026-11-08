---
type: regex
target: last_message
pattern: "^\\W*(in summary|to (recap|summarize|summarise|sum up)|overall)\\s*[,:]|\\b(i can also|would you like me to|shall i|let me know|feel free|hope (this|that) helps|happy to help)\\b|(^|[.!?:]\\s+)\\W*want me to\\b|\\bi can\\b[^.!?\\n]{0,120}\\bif you('d| would)? (like|want|prefer)\\b|\\b(it'?s|it is|this is|that'?s|that is) not (just|only|merely|simply)\\b[^.!?\\n]{1,80}?(,|;|:| - )\\s*(but\\s+)?(it'?s|it is|this is|that'?s|that is)\\b"
flags: im
match: not_contains
---
