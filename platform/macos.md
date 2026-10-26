# Platform profile: macOS (zsh)

Shell conventions for a macOS workspace. Install it as
`.claude/rules/platform.md` in the workspace root; use `platform/windows.md`
instead on a Windows machine.

---

## Command execution

Prefer tool-native path arguments over `cd <dir> && <command>` chains. A single
invocation does not need approval for the directory change.

**Use these forms:**

- `git -C <path-to-repo> <subcommand>` — works for any git subcommand
- `npm --prefix <path-to-project> <script>`
- `swift build --package-path <path>`, `xcodebuild -project <path> ...`
- `dotnet build <path-to-sln>` — also `test`, `restore`, `publish`
- `pytest <path-to-tests>`

**Output trimming is fine and encouraged:** `2>&1 | tail -n <N>` keeps context
small. Apply it to the tool-native form:

- `git -C <repo> log --oneline 2>&1 | tail -n 20`
- `xcodebuild ... 2>&1 | tail -n 20`

**Fall back to `cd <dir> && <command>` only when:**

- the tool has no working-directory flag
- a script relies on relative paths that resolve from a specific cwd
- running an interactive or watch process that needs a stable cwd

When falling back, say briefly why.

---

## Python and the knowledge base

- Use `python3` with forward-slash paths.
- Homebrew's system Python is externally managed (PEP 668). Never
  `pip install` into it.
- The kb scripts need `sqlite-vec`, which lives in `kb/.venv`. `extract.py`
  (and `recall.py`, which imports it) detect a missing `sqlite_vec` and re-exec
  under `kb/.venv/bin/python`, so plain `python3 kb/scripts/<script>.py` works.

---

## Gotchas

- **`log` is a zsh builtin.** Call `/usr/bin/log` for the unified log
  (`/usr/bin/log show ...`); plain `log show` fails or misparses.
- **`=` at the start of a word expands in zsh.** `echo ==` fails with
  `= not found`. Quote separators: `echo "--"`.
- **Obsidian started by its CLI dies with the shell.** `vault_write.py`
  launches it detached with `open -a Obsidian` when it is not running. If you
  call the `obsidian` CLI directly, run `open -a Obsidian` first and wait about
  10 s.
