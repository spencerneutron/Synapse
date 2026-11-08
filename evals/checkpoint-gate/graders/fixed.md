---
type: llm
focus: { source: file, path: wc.py }
---
PASS if count_words() in this file returns 8 for "the quick  brown fox\njumps over  the dog\n" (runs of non-whitespace, so double spaces and newlines do not add words).
FAIL otherwise.
