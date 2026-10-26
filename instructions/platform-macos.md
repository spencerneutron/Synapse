# Synapse platform rules: macOS (zsh)

Synapse loads this at session start because this machine runs macOS.

## Command execution

Prefer tool-native path arguments over `cd <dir> && <command>` chains:

- `git -C <path-to-repo> <subcommand>`
- `npm --prefix <path-to-project> <script>`
- `swift build --package-path <path>`, `xcodebuild -project <path> ...`
- `dotnet build <path-to-sln>` (also `test`, `restore`, `publish`)
- `pytest <path-to-tests>`

Trim output with `2>&1 | tail -n <N>` on the tool-native form. Fall back to
`cd <dir> && <command>` only when the tool has no working-directory flag, a
script relies on cwd-relative paths, or an interactive or watch process needs a
stable cwd; say briefly why.

## Python

- Use `python3` with forward-slash paths. Homebrew's Python is externally
  managed (PEP 668): never `pip install` into it; use a venv.
- The `synapse` command finds a Python 3.11+ and keeps its own venv under the
  Synapse home; call `synapse ...`, not its scripts.

## Gotchas

- **`log` is a zsh builtin.** Call `/usr/bin/log` for the unified log.
- **`=` at the start of a word expands in zsh.** `echo ==` fails with
  `= not found`; quote separators: `echo "--"`.
- **Obsidian started by its CLI dies with the shell.** `synapse vault` launches
  it detached with `open -a Obsidian` when needed. If you call the `obsidian`
  CLI directly, run `open -a Obsidian` first and wait about 10 s.
