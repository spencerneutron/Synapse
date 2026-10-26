# Synapse platform rules: Windows (PowerShell)

Synapse loads this at session start because this machine runs Windows.

## Command execution

Prefer tool-native path arguments over `cd <dir>; <command>` chains:

- `dotnet build <path-to-sln>` (also `test`, `restore`, `publish`,
  `run --project <path>`); `dotnet test <path-to-sln> --no-build` after a build
- `git -C <path-to-repo> <subcommand>`
- `npm --prefix <path-to-project> <script>`
- `pytest <path-to-tests>`

Trim output with `2>&1 | Select-Object -Last <N>` on the tool-native form, for
example `dotnet build <sln> -c Debug --nologo 2>&1 | Select-Object -Last 6`.
Fall back to `cd <dir>; <command>` only when the tool has no working-directory
flag, a script relies on cwd-relative paths, or an interactive or watch process
needs a stable cwd; say briefly why.

## Python

- Use `python` or the `py` launcher. `python3` is often the Microsoft Store
  stub, which exits silently.
- The `synapse` command finds a working Python 3.11+, forces UTF-8, and keeps
  its own venv under the Synapse home; call `synapse ...`, not its scripts.
- Write JSON to a file and pass `--from-file`. Multi-line JSON piped or passed
  inline through PowerShell breaks on quoting and triggers safety prompts.

## Gotchas

- **Obsidian is not auto-launched here.** Start Obsidian with the vault open
  before `/synapse:extract-session`.
