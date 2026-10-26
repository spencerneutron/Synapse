---
name: setup
description: Provision Synapse after the plugin is installed, or repair a broken install — creates the Synapse home (config, global store, Python venv, vector DB), checks Ollama, the embedding model, and Obsidian, and offers to import an old V1/v1.5 workspace. Use when the user asks to set up Synapse, when recall reports the DB is missing, or after a fresh install.
allowed-tools: Bash(synapse setup), Bash(synapse doctor *), Bash(synapse where *), Bash(synapse migrate * --dry-run)
---

# Setup Skill

## Purpose

Make the plugin's memory features work on this machine without touching
anything Synapse does not own. `synapse setup` writes only under the Synapse
home (`~/.claude/synapse/` unless `SYNAPSE_HOME` or `CLAUDE_CONFIG_DIR` says
otherwise) and is safe to re-run: it keeps an existing config and venv.

---

## Procedure

1. **Provision.** Run `synapse setup`. It:
   - creates `config.toml` only if missing (one global store, `main`, with the
     vault `Synapse`)
   - creates the store's archive folder and `vectors.db`
   - builds a venv with `sqlite-vec`
   - lists what is still missing for memory features

2. **Fill the gaps it lists, with consent.** For each item:
   - *Ollama missing or stopped* — tell the user to install it from
     https://ollama.com and start it. Do not install system software yourself.
   - *`nomic-embed-text` not pulled* — ask first (about 270 MB), then run
     `ollama pull nomic-embed-text`.
   - *`obsidian` CLI not on PATH* — tell the user to enable Obsidian's
     command-line interface.
   - *No vault named as configured* — ask whether to create a vault with that
     name in Obsidian, or to point the store at an existing vault by editing
     `vault` (and optionally `vault_path`) in `config.toml`.

3. **Check.** Run `synapse doctor` and walk the user through each `warn` or
   `error` line. Fix nothing it reports outside the Synapse home without the
   user's explicit go-ahead; most fixes there are the user's call.

4. **Import old memory (when doctor reports `old-install`).** Show the plan
   first with `synapse migrate --from "<dir>" --dry-run`. If the user agrees,
   run it without `--dry-run`. Migration copies; it never changes the old
   workspace. Afterwards run `synapse backfill --dry-run` and, with consent,
   `synapse backfill` to embed sessions the old install never embedded.

5. **Split stores only on request.** One global store is the default. If the
   user wants a project kept apart, add a `[stores.<name>]` table to
   `config.toml` and a `.synapse.toml` with `store = "<name>"` at that
   project's root; confirm with `synapse where` from inside the project.

---

## Output Behavior

Report what was created or kept, what is still missing and who must act, and
the doctor summary line. Keep it to the facts the user needs to act on.
