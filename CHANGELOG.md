# Changelog

## 1.5 — 2026-10-26

Consolidates V1 into one portable repo. No new memory or retrieval features.

### Changed

- **`AGENTS.md` is the only instruction file.** Claude Code reads it natively
  (2.1.277+), so `CLAUDE.md` is gone. V1's `CLAUDE.md` imported `AGENTS.md`
  and then repeated most of it; the two are now one deduplicated file.
- **OS-neutral core.** Shell conventions moved out of the instructions into
  `platform/macos.md` and `platform/windows.md`, installed as
  `.claude/rules/platform.md`. V1 mandated PowerShell while its memory skills
  said macOS and that the PowerShell rules did not apply.
- **One home for planning files:** `.claude-work/current/`. V1 gave three
  different answers.
- **`/plan-session` is project-neutral.** The hard-wired roadmap sync became
  a generic `## Session hooks` section that any project's `PLAN.md` can list.
- **`recall` and `extract-session` skills** defer to the platform profile
  instead of assuming macOS.
- **Vault name is configurable** with `SYNAPSE_VAULT` (default `Synapse`).
- The Agent tool replaces the old "Task tool" name; example project names in
  `backfill.py` are generic.

### Added

- **Waves and model right-sizing** in `AGENTS.md`: implementation,
  verification, research, and adversarial-review waves, one writer per file
  set, and model tiers per wave. Rebuilt from the V1 design notes. This
  reverses V1's rule that sub-agents never write to the workspace:
  implementation waves now write, one agent per set of files.
- **`emission-contract` skill** (late-bound directive plus exemplars) and the
  **`emission_check.py` Stop hook** with a pattern file. Rebuilt from the V1
  design notes; the originals were not available.
- `AGENTS.md` lifecycle table and a pointer to `/workflow-recovery` for
  interrupted multi-agent runs.
- `templates/` (PLAN, EXECUTION, NOTES, Stop-hook settings), `docs/setup.md`,
  `docs/architecture.md`, `kb/requirements.txt`, and `examples/`.

### Fixed

- `backfill.py` started `extract.py` with a hard-coded `python`, which does
  not exist on stock macOS; it now uses the running interpreter.
- `/recall` no longer offers `--type session` (Session notes are never
  embedded); `vault_write.py`'s docstring shows `note-exists <folder> <name>`.

### Removed

- Project-specific skills (`deploy`, `roadmap-sync`, `device-log-triage`).
  They belong to a single app, not the harness.

## 1.0 — 2026 (unreleased)

The harness as it ran day to day:

- `CLAUDE.md` + `AGENTS.md` instructions.
- Session skills: `/plan-session`, `/end-session`.
- Memory skills: `/recall`, `/extract-session`, backed by `extract.py`,
  `recall.py`, `vault_write.py`, and `backfill.py`.
- `workflow-recovery` and `language-sweep`.
- An emission contract with a Stop hook, and the multi-agent wave rules.
