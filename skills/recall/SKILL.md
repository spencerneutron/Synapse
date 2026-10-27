---
name: recall
description: Use to surface relevant prior sessions, decisions, and patterns from the local knowledge base. Returns ranked snippets with source paths — not full content. Treat results as navigation hints, not context.
allowed-tools: Bash(synapse recall *), Bash(synapse where *)
---

# Recall Skill

## Purpose

Query the local vector database to find prior work relevant to the current
task. Avoids reloading large amounts of past context into the working session;
instead surfaces *pointers* to where relevant prior thinking lives.

---

## Environment

`synapse recall` searches the **active store** (`synapse where` shows which
one and why). It runs from any folder and picks its own Python and venv. The
local **Ollama** server must be running with `nomic-embed-text` pulled, since
recall embeds the query before searching.

---

## When to Use

Use this skill when:

- The user asks to recall, look up, or find prior work ("/recall X", "have we
  done X before", "what did we decide about X")
- A topic in the current planning session may have been worked on before
  (proactive triggers are defined in the Synapse rules — Local Knowledge Recall)
- A decision is being made that resembles a prior decision

Do **not** use this skill:

- For information already present in the current `PLAN.md` / `EXECUTION.md`
- When the same topic was already recalled earlier in this session, or an
  automatic hint ("Synapse recall (automatic)") already surfaced it: read
  that hint's source instead. Run this skill when you need more hits,
  filters, or a different query than the prompt itself
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

### 2. Run the search

Run from the workspace root:

```
synapse recall "<query>" --format text
```

Optional filters when relevant:
- `--project <name>` — limit to one project's archives
- `--type decision|pattern|archive` — limit to one note type (Session notes
  are not embedded)
- `--mode hybrid|vector|keyword` — default `hybrid` (meaning and exact words
  together); `keyword` for an exact identifier, file name, or issue number
- `--include-superseded` — also return replaced decisions, labeled
- `--top-k N` — default 5; raise to 8–10 for broader scans, lower to 3 for
  precision-critical lookups
- `--since YYYY-MM-DD` — only chunks embedded on or after that date
- `--scope all|local|shared` — default `all`: the active store plus its
  teams' shared notes; `local` or `shared` for one side only

Filters are exact and run inside the search; `--project` ignores case.
Superseded decisions are hidden unless `--include-superseded` is passed.

### 3. Read the output structure

Each result is one ranked hit:

```
  N. [score] breadcrumb  (match)
     source path
     project: X  type: Y
     shared: <team> (<author>)   (only for a teammate's shared note)
     SUPERSEDED by <note>        (only with --include-superseded)
     snippet (200 chars max)
```

- **Score** is 0.0–1.0 cosine similarity. Above ~0.55 is a strong match.
  A cluster of similar scores (e.g., all 0.62–0.65) usually means the
  query is too generic or the corpus is small — none of the hits is
  dramatically better than the others.
- **Match** says which search found the hit: `vector` (meaning),
  `keyword` (exact words), or `both`. A `keyword` hit with a low score can
  still be the right one for an identifier query.
- **Breadcrumb** shows the file and the heading path to the chunk.
- **Source path** is the archive file or vault note the chunk came from.
  Archive files print as full paths in the store. Vault notes print as
  `vault/<Folder>/<note>.md` unless the store's config sets `vault_path`.
- **Snippet** is truncated. The full chunk content is *not* shown by design.

### 4. Decide what to do with each result

For each hit, judge whether the snippet is genuinely relevant to the
current task:

- **Clearly relevant**: read the source path with the file-reading tool.
  Apply learnings to the current task by **citing the source** and
  paraphrasing the prior decision. Example:
  > "We addressed something similar in
  > `archive/workspace/PLAN_2026-04-23-1645.md` — the decision was to
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
  See `archive/workspace/PLAN_2026-04-23-1645.md` for original context.
```

---

## Output Behavior

When invoked explicitly by the user (e.g. "/recall X" or "look up X"):

- Show the user the top 1–3 hits as a brief summary (breadcrumb + path +
  one-line interpretation), so they can see what was found.
- Then either continue the conversation using the recall as background, or
  stop and let the user direct next steps. Match the user's request.

When invoked proactively (per the Synapse rules' recall triggers):

- Do **not** announce the recall call or list results to the user.
- Apply relevant findings silently when planning, citing source paths
  when the prior knowledge actually shapes the current decision.
- If nothing relevant came back, proceed as if no prior knowledge exists.

---

## Failure Handling

- If `synapse recall` exits with `error: DB not found` — the store hasn't
  been set up. Suggest `/synapse:setup` and tell the user no prior sessions
  are available to query.
- If `synapse recall` reports "no results" — proceed without prior context.
  Mention the empty result only if the user explicitly asked for a recall.
- If Ollama is unreachable, `synapse recall` prints a clear error. Surface it
  to the user; do not fall back to guessing prior content.