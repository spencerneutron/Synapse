---
name: language-sweep
description: Clean up external-facing English. Two modes. Default (strict)
  rewrites toward ASD-STE100 Simplified Technical English for docs, release
  notes, error messages, and API reference. Lite mode removes AI tics,
  verbosity, and jargon while keeping the author's voice, for marketing
  copy, landing pages, and announcements. Use when the user asks for a
  language sweep, STE, Simplified Technical English, controlled language,
  plain-language conversion, or de-AI-ifying prose.
---

# Language Sweep

## Mode selection

Read `modes/strict.md` unless the invocation contains "lite", "light",
or "soft". In that case read `modes/lite.md`.

Read one mode file. Never both.

If the target text is marketing or landing-page copy and the invocation
did not specify a mode, make a skilled estimation and choose lite if it holds up.

## Output contract

Output the rewritten text only. No diff, no rationale, no summary of
changes. Preserve the source formatting: headings stay headings, lists
stay lists, code blocks are untouched.

## Identifier exemption

Never rewrite product names, command names, API names, parameter names,
error codes, file paths, or code identifiers. These are exempt from every
rule in both modes.

## Default bias

When a change is not clearly an improvement, leave the text alone.