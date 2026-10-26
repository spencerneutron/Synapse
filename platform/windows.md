# Platform profile: Windows (PowerShell)

Shell conventions for a Windows workspace. Install it as
`.claude/rules/platform.md` in the workspace root; use `platform/macos.md`
instead on a Mac.

---

## Command execution

Prefer tool-native path arguments over `cd <dir>; <command>` chains. A single
invocation does not need approval for the directory change.

**Use these forms:**

- `dotnet build <path-to-sln>` — also `test`, `restore`, `publish`,
  `run --project <path>`
- `dotnet test <path-to-sln> --no-build` when a build just ran
- `git -C <path-to-repo> <subcommand>` — works for any git subcommand
- `npm --prefix <path-to-project> <script>`
- `pytest <path-to-tests>`

**Output trimming is fine and encouraged:** `2>&1 | Select-Object -Last <N>`
keeps context small. Apply it to the tool-native form:

- `dotnet build <path-to-sln> -c Debug --nologo 2>&1 | Select-Object -Last 6`
- `dotnet test <path-to-sln> --no-build 2>&1 | Select-Object -Last 6`

**Fall back to `cd <dir>; <command>` only when:**

- the tool has no working-directory flag
- a script relies on relative paths that resolve from a specific cwd
- running an interactive or watch process that needs a stable cwd

When falling back, say briefly why.

---

## Python and the knowledge base

- Use `python` (or the `py` launcher). Backslash and forward-slash paths both
  work in the kb scripts.
- The kb scripts need `sqlite-vec`, which lives in `kb\.venv`. `extract.py`
  (and `recall.py`, which imports it) re-exec under
  `kb\.venv\Scripts\python.exe` when the current interpreter lacks it.
- The scripts force UTF-8 on stdout/stderr, because PowerShell defaults to
  cp1252 and mangles non-ASCII snippets.
- Write JSON specs to a file and pass `--from-file`. Multi-line JSON piped or
  passed inline through PowerShell triggers quoting and safety-prompt problems.

---

## Gotchas

- **Obsidian is not auto-launched.** `vault_write.py` starts Obsidian only on
  macOS. Start Obsidian with the vault open before `/extract-session`.
- **The Stop hook command.** The settings template calls `python3`. Change it
  to `python` (or `py -3`) when you install on Windows.
