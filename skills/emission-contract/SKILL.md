---
name: emission-contract
description: Reference text of the emission contract that Synapse's Stop hook enforces on the final user-facing message of a turn (shape, length, banned patterns) with before/after exemplars. The hook's block reason already carries the rules, so no per-turn load is needed; read this for the full text or the exemplars. Not for code, files, commit messages, or sub-agent briefs.
---

# Emission Contract

This contract applies to the final user-facing message of a turn. The
plugin's Stop hook enforces it: when the message breaks a mechanical rule, the
hook blocks the stop once and its reason carries the directive below in
compact form, plus what it found (Synapse rules — Emission). This file is the
reference text; keep its Directive in step with `directive` in the plugin's
`hooks/emission_patterns.json`.

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
6. **Plain words.** None of the tics below (delve, tapestry, "testament to",
   "it's worth noting"). No emoji.
7. **Waiting on an agent.** When a dispatched agent is still running, the
   message is one line naming what you wait for. Its report or the user's next
   message resumes you; verify the report before calling the work done.

---

## Mechanically checked

The plugin's Stop hook (`hooks/emission_check.py`) blocks the turn once and asks
for a rewrite when the message contains any of these:

- Praise or filler openers: "Great question", "Sure!", "Certainly,",
  "I'd be happy to"
- Pleasantry closers in the last paragraph: "Let me know if", "Feel free to",
  "Hope this helps"
- A summary paragraph at the end, opening with "In summary", "To recap",
  "To summarize", or "Overall,"
- Offers in the last paragraph: "I can also", "Would you like me to",
  "Want me to", "Shall I", "I can … if you'd like", "I can fix any of
  these", "… if you want one", "If you need any of these". State the next
  step, or ask the one decision directly ("Merge it now?")
- "It's not just X, it's Y" in its plain forms ("This is not only X; it is Y")
- More than 3 headings in a message under 500 words
- Tics: delve, tapestry, "testament to", "it's worth noting",
  "in today's … world"
- Emoji: pictographs, ✅, ❌, ✨
- Angle-bracket placeholders in prose, such as `<numbers>`: some terminals
  (PowerShell) show them as `&lt;numbers&gt;`. Write "skip 2", "N", or the
  real value.

The hook reads prose only. Fenced code (```` ``` ```` or `~~~`), inline code,
and `>` quotes are skipped; indented code blocks are not. Tic words match in
lowercase only, so names such as the Delve debugger pass. Patterns live in
the plugin's `hooks/emission_patterns.json`.

## Judgment only

The hook cannot see these; avoid them anyway:

- "Not X but Y" contrasts in other wordings
- Rhetorical questions the next sentence answers
- Three-item lists where the third item is padding
- Em dashes used for emphasis where a period works
- A closing paragraph that summarizes the message without a marker phrase
- Bold labels standing in for headings in a short message

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
> `synapse extract status 2026-10-26-1400`.

**Before** (waiting on an agent)

> I've dispatched the reviewer and will keep polling its output until it
> finishes, then report back.

**After**

> Waiting on the reviewer's report for the gate change; I will verify it when
> it lands.
