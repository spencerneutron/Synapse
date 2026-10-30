---
type: regex
target: { source: file, path: exporters/__init__.py }
flags: s
pattern: '^(?=.*["'']csv["'']\s*:)(?=.*["'']json["'']\s*:)(?=.*["'']text["'']\s*:)'
---
