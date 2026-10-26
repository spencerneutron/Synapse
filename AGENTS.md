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
| `tests/`, `tools/`, `docs/`, `templates/`, `examples/` | As named |

## Rules for changes

- **Instructions:** after editing `instructions/*.md`, run
  `python3 tools/build_context.py`. Each file must stay under 10,000
  characters (Claude Code's SessionStart cap); keep `core.md` under 9,500.
- **Locations:** only `lib/synapse/paths.py` decides where data lives. Store
  paths in the DB stay relative (`archive/<project>/…`, `vault/<Folder>/…`).
- **Skills call the CLI** (`synapse …`), never script paths. Name new skills
  without a `synapse-` prefix; the plugin namespaces them.
- **Non-destructive:** nothing may write outside the Synapse home, the
  project's working files, or the vault. New overlap risks get a check in
  `lib/synapse/doctor.py` and a row in INSTALL.md's preflight table.
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

Try the plugin without installing it: `claude --plugin-dir .`. Run the CLI
against a throwaway home: `SYNAPSE_HOME=$(mktemp -d) bin/synapse setup`.

## Release

Bump `version` in `.claude-plugin/plugin.json` (users receive updates only
when it changes), add a CHANGELOG entry, then tag with `claude plugin tag`.
