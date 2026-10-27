# AGENTS.md — working on the Synapse repo

This file is for agents changing this repository. **If the user asked you to
install Synapse, stop here and follow [INSTALL.md](INSTALL.md).** The rules
Synapse gives every session are in `instructions/`, not here.

## Layout

| Path | What |
|------|------|
| `.claude-plugin/` | Plugin manifest (version lives here) and the marketplace manifest |
| `instructions/` | Always-on rules, injected by the SessionStart hook |
| `hooks/` | `hooks.json`, `session_start.sh`, prebuilt `context/*.json`, the Stop hook and its patterns |
| `bin/synapse` | CLI entry on the Bash PATH; runs `lib/synapse/cli.py` through `lib/py.sh` |
| `lib/synapse/` | `paths.py` (all location logic), the memory pipeline, setup, doctor, archive, migrate |
| `skills/` | Plugin skills, invoked as `/synapse:<name>` |
| `agents/` | Role sub-agents, invoked as `subagent_type: synapse:<role>`; each body carries its own rules |
| `evals/` | `claude plugin eval` cases: fixture script, prompt, graders |
| `tests/`, `tools/`, `docs/`, `templates/`, `examples/` | As named |

## Rules for changes

- **Instructions:** after editing `instructions/*.md`, run
  `python3 tools/build_context.py`. Each file must stay under 10,000
  characters (Claude Code's SessionStart cap); keep `core.md` under 9,500.
- **Locations:** only `lib/synapse/paths.py` decides where data lives. Store
  paths in the DB stay relative (`archive/<project>/…`, `vault/<Folder>/…`).
- **Agents:** sub-agents never see `instructions/`; put the rules a role needs
  in its body. Allowlist tools with a Bash fallback for search (some Claude
  Code builds ship no Grep/Glob). Plugin agents ignore `permissionMode`,
  `hooks`, and `mcpServers`.
- **Skills call the CLI** (`synapse …`), never script paths. Name new skills
  without a `synapse-` prefix; the plugin namespaces them.
- **Non-destructive:** nothing may write outside the Synapse home, the
  project's working files, the vault, or a team's notes folder. New overlap
  risks get a check in `lib/synapse/doctor.py` and a row in INSTALL.md's
  preflight table.
- **Store schema:** a change to `vectors.db` bumps `extract.SCHEMA_VERSION`
  and extends `synapse extract upgrade` (backup first, no re-embedding,
  verify every vector). Measure retrieval changes with `synapse
  recall-check` against a golden set before and after.
- **Python:** 3.11+, stdlib only except `sqlite-vec`.
- **No personal data:** no home paths, usernames, machine ids, or private
  links outside `examples/` (CI scans for them).

## Test

```bash
python3 -m unittest discover -s tests
```

```bash
python3 tools/build_context.py --check
```

```bash
claude plugin validate . --strict
```

Try the plugin without installing it: `claude --plugin-dir .`.

## Evals (cost money: run only when the user asks)

`evals/` holds a `claude plugin eval` suite of real Claude sessions. "Run the
tests" means the unit tests above, never the evals. Run evals only when the
user explicitly asks, and say the cost first (about $1.50-2.00 per full run).
Use the wrapper, which refuses to start without `--yes`, keeps reports local,
and caps cost:

```bash
tools/run-evals.sh --yes
```

Never run a bare `claude plugin eval`: by default it runs 3 runs per case in
two arms and publishes its report to claude.ai.

The bench runs every case with Synapse and without it (the no-plugin
baseline), builds the fixture homes it needs, and prints what Synapse adds
(about $6, capped at $13.50):

```bash
tools/run-bench.sh --yes
```

`python3 tools/eval-report.py RUN.json...` reports with vs without;
`--compare OLD.json NEW.json` compares two runs. A grader that only means
something with Synapse (a `synapse:<role>` dispatch, a Synapse rule's
offer) carries `arm: with-only`, so it is shown but not scored.

The `slice-d` cases need a memory: build fixture homes with
`python3 tools/build_eval_home.py <dir> --triggers on|off` (uses Ollama), then
run `EVAL_SYNAPSE_HOME=<dir> tools/run-evals.sh --yes --tag slice-d`. Eval runs
cannot read files outside their workspace, so a hint's snippet is all the
agent sees of a memory there. Eval traces record `SessionStart` hook output
but not `UserPromptSubmit` output, so no grader can see a hint: measure it by
outcome, hints-on home against hints-off home. The `slice-e` case needs
`build_eval_home.py <dir> --triggers on --team`.

Eval sessions cannot run the `synapse` CLI (the plugin's `bin/` is not on
their PATH, and their sandbox blocks the Synapse home), so a CLI-driven skill
is checked live instead: `tools/live-check-share.sh --yes <team home>` runs
headless sessions with this repo as the plugin (about $0.30 per run). Run the
CLI against a throwaway home: `SYNAPSE_HOME=$(mktemp -d) bin/synapse setup`.

## Release

Bump `version` in `.claude-plugin/plugin.json` (users receive updates only
when it changes), add a CHANGELOG entry, then tag with `claude plugin tag`.
