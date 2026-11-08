---
type: llm
focus: { source: file, path: text.py }
---
PASS if slugify() in this file turns "  Hello,   World! " into "hello-world": lowercase, runs of non-alphanumeric characters collapsed to one hyphen, no leading or trailing hyphen.
FAIL otherwise.
