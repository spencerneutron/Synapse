---
name: emission-contract
description: Load immediately before writing the final user-facing message of a turn. Holds the output contract for that one message (shape, length, banned patterns) with before/after exemplars. Not for code, files, commit messages, or sub-agent briefs.
---

# Emission Contract

This contract applies to the one message you are about to write. It is loaded
late on purpose: its rules stay out of the context while the work happens
(`AGENTS.md` — Emission).

---

## Directive

1. **Lead with the outcome.** The first sentence is the answer, the result, or
   the blocker. Never what you are about to say.
2. **Report evidence, not effort.** Say what changed, what you ran, and what it
   showed. State a failure plainly, with its output.
3. **Size to the ask.** A quick question gets one to three sentences. Use
   headings only when the message has three or more distinct parts.
4. **Specifics over adjectives.** `path:line`, numbers with units, exact
   commands in fenced blocks.
5. **End on substance.** At most one concrete next step or one question. No
   recap, no offers, no pleasantries.
6. **Plain words.** None of the tics below. No emoji.

---

## Mechanically checked

The Stop hook (`.claude/hooks/emission_check.py`) blocks the turn once and asks
for a rewrite when the message contains any of these:

- Praise or filler openers: "Great question", "Sure!", "Certainly,",
  "I'd be happy to"
- Pleasantry closers in the last paragraph: "Let me know if", "Feel free to",
  "Hope this helps"
- Tics: delve, tapestry, "testament to", "it's worth noting",
  "in today's … world"
- Emoji: pictographs, ✅, ❌, ✨

The hook reads prose only. Fenced code (```` ``` ```` or `~~~`), inline code,
and `>` quotes are skipped; indented code blocks are not. Tic words match in
lowercase only, so names such as the Delve debugger pass. Patterns live in
`.claude/hooks/emission_patterns.json`.

## Judgment only

The hook cannot see these; avoid them anyway:

- "It's not just X, it's Y" and its variants
- Rhetorical questions the next sentence answers
- Three-item lists where the third item is padding
- Em dashes used for emphasis where a period works
- A closing paragraph that summarizes the message

---

## Exemplars

**Before**

> Great question! I've gone ahead and looked into the failing test. It turns
> out the issue was related to a timezone mismatch. I've fixed it and
> everything should be working now. Let me know if you need anything else! 🎉

**After**

> Fixed: `testWeekBoundary` failed because the test built dates in UTC while
> `Scheduling` uses the device time zone. `SchedulingTests.swift:88` now uses
> `Calendar.current`, and all 236 unit tests pass.

**Before** (quick question)

> ## Answer
>
> Certainly! It's worth noting that there are a few ways to approach this.
> The recall script supports several filters, one of which is a type filter.

**After**

> Yes. `recall.py --type decision` returns only promoted Decision notes.

**Before** (could not verify)

> I've made the changes and the embedding step should work fine now.

**After**

> The change is in `extract.py:212`, but I could not run it: Ollama refused
> the connection on `localhost:11434`. Start it with `ollama serve`, then run
> `python3 kb/scripts/extract.py status 2026-10-26-1400`.
