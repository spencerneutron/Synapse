# Architecture

Synapse is a Claude Code plugin that gives every session, in any project, the
same operating loop: plan, execute, archive, and extract, with prior knowledge
recalled in later sessions, on demand and automatically, and optionally
shared with a small team.

Instructions decide *when*; skills decide *how*; Python does the mechanics;
hooks enforce what instructions can only request.

---

## Session lifecycle

1. **Plan** (`/synapse:plan-session`). Explore the repos with batched reads and a
   sub-agent for cross-repo searches; run any session hooks the plan lists;
   `/synapse:recall` when the work resembles prior work. Write
   `.claude-work/current/PLAN.md` (strategy, constraints, Decision Log) and
   `EXECUTION.md` (the active task).
2. **Execute.** Small, verifiable, localized steps, in waves of role-specific
   agents (implementation, verification, research, adversarial review).
   Frontier models plan; right-sized models execute. `EXECUTION.md` updates
   often; `PLAN.md` only for durable decisions.
3. **Emit** (every turn end). The `synapse:emission-contract` skill loads just before
   the user-facing message. A Stop hook checks the message and forces one
   rewrite on a violation.
4. **Archive** (`/synapse:end-session`). `synapse archive` copies `PLAN` and
   `EXECUTION` into the active store as `archive/<project>/<FILE>_<id>.md`
   under a session ID such as `2026-05-01-1515`; the skill adds `NOTES`.
5. **Extract** (`/synapse:extract-session`). At teardown, while context is fresh,
   Claude proposes Decision and Pattern notes and the user confirms once.
   Promoted notes and a Session note go to the vault; the archive and new
   notes are embedded; a `.processed/<id>.json` marker records the run.
6. **Recall** (`/synapse:recall`). Later sessions, in any project, query the
   active store's vector DB and get ranked snippets with source paths:
   pointers into the archive, not loaded context. A `UserPromptSubmit` hook
   also adds up to three such pointers to a prompt when something in the
   store scores at least 0.70, and a session-start note names archived
   sessions never extracted.
7. **Share** (`/synapse:share`, optional). Chosen Decisions and Patterns pass
   a scrub gate and the user's approval, then go to a team folder (a git
   repo or a synced folder). Each member's sessions sync it in the
   background and index it locally, so teammates' notes join recall,
   labeled, with the member's own decisions winning a conflict.

`/synapse:workflow-recovery` sits outside the loop: when a background workflow dies,
it harvests finished agents' results from disk before anything is relaunched.

---

## Components

| Layer | Component | Role |
|-------|-----------|------|
| Package | `.claude-plugin/` | Plugin manifest plus a marketplace manifest, so the repo installs with one command at user scope |
| Instructions | `instructions/core.md` | Always-on rules (lifecycle, planning, validation, waves and model right-sizing, recall, team-note, and emission triggers), injected by a `SessionStart` hook; under 10,000 characters |
| Instructions | `instructions/platform-*.md` | Shell conventions for macOS or Windows, picked by the same hook from `uname` |
| Skills | `/synapse:plan-session`, `/synapse:end-session` | Session start/resume and archiving |
| Skills | `/synapse:recall`, `/synapse:extract-session` | Memory read and write; extraction holds the promotion gate |
| Skills | `/synapse:share` | Scrub, show, and share approved notes with a team; ask before each push |
| Skills | `synapse:emission-contract` | Late-bound output contract: a compact directive plus exemplars |
| Skills | `/synapse:workflow-recovery` | Salvage results from an interrupted multi-agent run |
| Skills | `/synapse:language-sweep` | Prose cleanup in strict ASD-STE100 or lite marketing-copy mode |
| Skills | `/synapse:setup`, `/synapse:doctor` | Provision the Synapse home; read-only health and conflict report |
| Agents | `synapse:implementer`, `verifier`, `researcher`, `reviewer`, `scout` | Wave roles with their own models and tool limits; each body carries the rules its job needs, because sub-agents do not receive the `SessionStart` rules |
| Hooks | `emission_check.py` (Stop) | Blocks a non-compliant final message once and asks for a rewrite; allows the stop on `stop_hook_active` or any internal error |
| Hooks | `synapse recall-hint` (UserPromptSubmit), `synapse pending --hook` and `synapse shared hook` (SessionStart) | Automatic recall hints, the extraction reminder, and the team sync (started in the background); all fail silently |
| CLI | `bin/synapse` → `lib/synapse/` | On the Bash PATH from any folder: `where`, `setup`, `doctor`, `archive`, `recall`, `recall-check`, `recall-hint`, `pending`, `extract` (incl. `upgrade`, `supersede`), `vault`, `share` (`scrub`, `lint`, `add`), `shared` (`init`, `join`, `sync`, `status`, `retract`, `push`), `backfill`, `migrate`; `lib/py.sh` finds Python 3.11+ |
| Resolver | `lib/synapse/paths.py` | The only code that decides locations: home, store, project, archive, DB, vault |
| Store | `~/.claude/synapse/stores/<store>/archive/<project>/` | Canonical session history |
| Store | `~/.claude/synapse/stores/<store>/vectors.db` | Schema v2: sqlite-vec vectors with project/type/status metadata filtered inside the search, an FTS5 keyword index, `nomic-embed-text` via Ollama, cosine distance, store-relative source paths, supersession status |
| Store | The store's Obsidian vault (default `Synapse`) | Flat folders: Sessions, Decisions, Patterns, Projects |
| Team | A team's notes folder (a clone under `~/.claude/synapse/shared/<team>/`, or a synced folder) | `Decisions/`, `Patterns/`, `Retracted/`: the scrubbed notes members share |
| Team | `~/.claude/synapse/shared/<team>/vectors.db` | Each member's local index of the team folder, rebuilt by content hash; never shared |
| Evals | `evals/`, `tools/run-bench.sh`, `tools/eval-report.py` | A `claude plugin eval` suite run with and without Synapse; run on demand, never in CI |
| Runtime | Claude Code, auto mode | Controls live in the harness instead of permission prompts |

**Stores.** One global store (`main`) by default. A project can opt into
another with a `.synapse.toml` at its root (`store = "<name>"`), and
`SYNAPSE_STORE` overrides both for a session. A store keeps its archive, vector
DB, and vault together, so splitting a project splits all three. Teams
(`[shared.<team>]` in `config.toml`) are searched alongside the stores they
list, or every store by default.

---

## Operating principles

**Memory**

- Archives are canonical; the vault and the vector DB are regenerable projections.
- Deterministic mechanics in Python, judgment in skills. Scripts never decide what matters.
- Conservative promotion. A Decision must be a choice, carry rationale, stay
  durable, and be non-obvious. A Pattern must transfer across projects and condense.
- Idempotency everywhere: content-hash chunk dedup, `.processed` markers,
  always-replace for edited notes.
- Fail loud: encoding errors, embedding-model mismatches, and unreachable
  services error out rather than write bad data.
- Local by default: no egress beyond Claude Code itself, except the
  one-time `sqlite-vec` download from PyPI during setup. With a team, only
  the notes the user approves leave the machine, through the team's git
  remote or sync service, and teammates' notes pass the same scrub gate on
  the way in.
- Recall results are navigation, not context.

**Execution**

- Plan first; explore and reuse existing patterns before introducing new ones.
- Smallest localized change; no unrelated refactors or scope growth.
- Every change carries a run path, an expected outcome, and a failure signal.
- Token discipline: no re-reading unchanged files; conclusions cached in `PLAN.md`.
- When blocked: re-evaluate assumptions, search alternatives, simplify, log the blocker.

**Orchestration**

- Batch parallel tool calls during exploration.
- Sub-agents for bounded investigations; waves of role-specific agents for
  implementation, verification, research, and adversarial review.
- Right-size the model to the wave: frontier for planning, cheaper for execution.
- Move controls into the harness, then remove permission prompts (auto mode).

**Output**

- Keep style constraints out of the reasoning context.
- Bind the output contract late, through a skill loaded just before emission.
- Enforce deterministically with a Stop hook rather than trusting the model to self-trigger.

---

## Operating loop

The execution loop repeats per wave inside a session; the memory loop closes
across sessions when `vectors.db` feeds the next `/recall`.

```mermaid
flowchart TD
    T([Task arrives]) --> PS

    subgraph P["Plan"]
        PS["/synapse:plan-session<br/>parallel repo exploration<br/>+ session hooks"] --> RQ{"Resembles<br/>prior work?"}
        RQ -- yes --> RC["/synapse:recall<br/>ranked snippets + paths"]
        RQ -- no --> PF
        RC --> PF["Write PLAN.md<br/>+ EXECUTION.md"]
    end

    subgraph X["Execute"]
        PF --> WV["Wave: implement / verify /<br/>research / adversarial review"]
        WV --> VL{"Run path, expected outcome,<br/>failure signal satisfied?"}
        VL -- no --> FB["Re-evaluate, simplify,<br/>log blocker in PLAN.md"]
        FB --> WV
        VL -- yes --> UP["Update EXECUTION.md;<br/>durable decisions to PLAN.md"]
    end

    subgraph E["Every turn end"]
        UP --> EC["Load emission-contract skill"]
        EC --> DR["Draft user-facing message"]
        DR --> SH{"Stop hook:<br/>contract violated?"}
        SH -- yes --> EC
    end

    SH -- no --> DN{"Session<br/>done?"}
    DN -- no --> WV
    DN -- yes --> ND

    subgraph M["Memory"]
        ND["/synapse:end-session"] --> AR[("Store archive<br/>canonical")]
        AR --> XS["/synapse:extract-session<br/>propose, confirm once"]
        XS --> GT{"Choice, rationale,<br/>durable, non-obvious?"}
        GT -- yes --> VT[("Obsidian vault<br/>Decisions, Patterns, Sessions")]
        GT -- no --> AO["Stays in archive only"]
        AR --> EM["synapse extract"]
        VT --> EM
        BF["synapse backfill / migrate"] --> EM
        EM --> DB[("vectors.db<br/>sqlite-vec + nomic-embed-text")]
    end

    DB -. semantic query .-> RC
```

The Session note is written to the vault on every extraction and is left out
of the gate above for readability. The emission check fires at every turn end,
not only at session close. Not drawn: the automatic hint (the
`UserPromptSubmit` hook queries the same `vectors.db` on each prompt) and
team sharing (approved notes go to a team folder that every member indexes
next to their own store).

---

## V2 status

V1 enforced the output contract with a hook but left recall, extraction, and
role selection to instructions. V2 took each seam below in a measured slice
([plan and results](design/v2.md)); the last column is what could come next.

| Seam | Today (2.3) | Further option | Trade-off |
|------|------------|-----------|-----------|
| Recall triggering | **Done in V2 slice D:** a `UserPromptSubmit` hook adds up to three hints scoring ≥ 0.70, once per session, failing silently | Per-project thresholds | Calibrated on the author's store: 0 of 24 unrelated prompts hinted |
| Extraction | **Done in V2 slice D:** a session-start reminder lists archived sessions never extracted; the user still runs `/synapse:extract-session` | Auto-embed pending archives without promotion | Nothing is forgotten silently; judgment stays with a live session |
| Role orchestration | **Done in V2 slice C:** five plugin agents with per-role models, tool limits, and their own rules; measured with an eval suite | Hooks that route work to a role | Right-sizing is config; agent files to maintain |
| Memory hygiene | **Done in V2 slice 1:** `synapse extract supersede` marks the old decision in the DB and its front matter; recall hides it by default | Detect likely supersessions during extraction | Fewer near-duplicate decisions left active |
| Retrieval | **Done in V2 slice 1:** hybrid keyword + vector with reciprocal rank fusion; exact, case-insensitive filters inside the search | Tuned chunking; a cross-encoder re-ranker | Measured with `synapse recall-check` |
| Memory scope | **Done in V2 slice E:** optional teams share Decisions and Patterns through a git repo or a synced folder, behind a scrub gate and per-note approval, with provenance and local-first ranking | Encryption, access control beyond the git host's | Team leverage; a leak cannot be unshared from teammates' clones. **Gate:** the share step scrubs paths, secrets, identifiers, and session-local references (bare `#17`, "Wave B", "this session"), and sync re-checks every incoming note |
| Evaluation | **Done in V2 slice A:** a `claude plugin eval` suite (core loop, role agents, triggers, teams) run with and without Synapse by `tools/run-bench.sh`, reported by `tools/eval-report.py` ([V2 plan](design/v2.md)) | Evals in CI; more cases per seam | Each run costs money; benchmark upkeep is real work |

Closed since V1: v1.5 merged the instruction files and split out the platform
conventions; v1.6 packaged Synapse as a user-scope plugin with a global store
([design](design/packaging.md)); V2 slices 1, C, D, E, and A followed
(2.0.0 to 2.3.0). Still open: slice F, reach (an MCP server for recall
outside Claude Code, a Linux platform profile, other agents' manifests).
