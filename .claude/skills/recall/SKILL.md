---
name: recall
description: Use to surface relevant prior sessions, decisions, and patterns from the local knowledge base. Returns ranked snippets with source paths — not full content. Treat results as navigation hints, not context.
---

# Recall Skill

## Purpose

Query the local vector database to find prior work relevant to the current
task. Avoids reloading large amounts of past context into the working session;
instead surfaces *pointers* to where relevant prior thinking lives.

---

## Environment

Commands below say `python3`; use the Python named in the active platform
profile (`.claude/rules/platform.md`). `recall.py` needs `sqlite-vec`, which lives only in
`kb/.venv`; it imports `extract.py`, which detects a missing `sqlite_vec` and
re-execs under `kb/.venv` for you. So invoke it with the plain interpreter —
no need to name the venv one, and never pip-install into a system Python. The
local **Ollama** server must be running with `nomic-embed-text` pulled, since
recall embeds the query before searching.

---

## When to Use

Use this skill when:

- The user asks to recall, look up, or find prior work ("/recall X", "have we
  done X before", "what did we decide about X")
- A topic in the current planning session may have been worked on before
  (proactive triggers are defined in `AGENTS.md` — Local Knowledge Recall)
- A decision is being made that resembles a prior decision

Do **not** use this skill:

- For information already present in the current `PLAN.md` / `EXECUTION.md`
- When the same topic was already recalled earlier in this session
- For generic / well-known knowledge (regular reasoning suffices)

---

## Procedure

### 1. Form a focused query

Recall works on semantic similarity, not keyword matching. The query should
describe the *concept* being looked up in 2–6 words. Examples:

- Good: `"retry strategy http client"`
- Good: `"obsidian cli launch behavior"`
- Good: `"sqlite-vec embedding model choice"`
- Bad: `"what was the thing we decided about that one project"` (no concept)
- Bad: `"all decisions"` (too broad — every chunk is loosely matched)

### 2. Invoke recall.py

Run from the workspace root:

```
python3 kb/scripts/recall.py "<query>" --format text
```

Optional filters when relevant:
- `--project <name>` — limit to one project's archives
- `--type decision|pattern|archive` — limit to one note type (Session notes
  are not embedded, so `--type session` returns nothing)
- `--top-k N` — default 5; raise to 8–10 for broader scans, lower to 3 for
  precision-critical lookups
- `--since YYYY-MM-DD` — only recent results

### 3. Read the output structure

Each result is one ranked hit:

```
  N. [score] breadcrumb
     source path
     project: X  type: Y
     snippet (200 chars max)
```

- **Score** is 0.0–1.0 cosine similarity. Above ~0.55 is a strong match.
  A cluster of similar scores (e.g., all 0.62–0.65) usually means the
  query is too generic or the corpus is small — none of the hits is
  dramatically better than the others.
- **Breadcrumb** shows the file and the heading path to the chunk.
- **Source path** is the archive or vault note the chunk came from.
- **Snippet** is truncated. The full chunk content is *not* shown by design.

### 4. Decide what to do with each result

For each hit, judge whether the snippet is genuinely relevant to the
current task:

- **Clearly relevant**: read the source path with the file-reading tool.
  Apply learnings to the current task by **citing the source** and
  paraphrasing the prior decision. Example:
  > "We addressed something similar in
  > `.claude-work/archive/PLAN_2026-04-23-1645.md` — the decision was to
  > use sqlite-vec because it has no daemon overhead. Same constraint
  > applies here, so I'll use the same approach unless you want to
  > revisit."

- **Possibly relevant**: note the source path mentally; don't read it
  unless the current work hits a wall. Mention it in passing if it would
  help orient the user, but don't dive in proactively.

- **Not relevant**: ignore.

### 5. Never paste recall results into planning files

`PLAN.md` and `EXECUTION.md` should reference past work by **path and
brief paraphrase**, never by quoting recall output verbatim. The point of
recall is to find context, not to import it into the current session.

Bad:
```
## Decision Log
- Decision: Use sqlite-vec
  Rationale: [paste of full chunk text from recall]
```

Good:
```
## Decision Log
- Decision: Use sqlite-vec
  Rationale: Same as session 2026-04-23-1645 (lightweight, no daemon).
  See `.claude-work/archive/PLAN_2026-04-23-1645.md` for original context.
```

---

## Output Behavior

When invoked explicitly by the user (e.g. "/recall X" or "look up X"):

- Show the user the top 1–3 hits as a brief summary (breadcrumb + path +
  one-line interpretation), so they can see what was found.
- Then either continue the conversation using the recall as background, or
  stop and let the user direct next steps. Match the user's request.

When invoked proactively (per AGENTS.md triggers):

- Do **not** announce the recall call or list results to the user.
- Apply relevant findings silently when planning, citing source paths
  when the prior knowledge actually shapes the current decision.
- If nothing relevant came back, proceed as if no prior knowledge exists.

---

## Failure Handling

- If `recall.py` exits with `error: DB not found` — the knowledge base
  hasn't been initialized yet. Run `python3 kb/scripts/extract.py init`
  and tell the user no prior sessions are available to query.
- If `recall.py` reports "no results" — proceed without prior context.
  Mention the empty result only if the user explicitly asked for a recall.
- If Ollama is unreachable, recall.py will print a clear error. Surface it
  to the user; do not fall back to guessing prior content.