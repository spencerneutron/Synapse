# Branch details for plan-session

Read only the section whose condition `SKILL.md` names. Nothing here runs on
its own.

## Choose or start an effort

- The effort the user names wins. Otherwise match the task to the list. Ask
  only when two efforts fit.
- Take one up: `synapse effort resume <slug>`. Then read only
  `.claude-work/efforts/<slug>/PLAN.md` and `EXECUTION.md`, once, and extract
  objective, constraints, progress and prior decisions. Run `resume` only to
  move to another effort, or when the effort is `waiting` and the wait is
  over, not for the effort the session is already on.
- No effort fits: propose a slug (lower case, `a-z`, `0-9`, `-`) and run
  `synapse effort start <slug> --title "..."`. It creates PLAN.md and
  EXECUTION.md from the templates; fill them in.
- If the index shows an open effort untouched for 7 days or more, ask the
  user once whether it is done, parked or still open, and record the answer
  with the CLI (`done`/`cancel` only on their word).

## Status changes

Only through the CLI: `synapse effort wait <slug> --on "..."` or
`synapse effort park <slug>` when that is the state; `synapse effort done
<slug>` or `cancel <slug> --reason "..."` only on the user's word.

## Start the first effort

Neither `.claude-work/efforts/` nor `current/` planning files exist and the
task justifies structured planning: start an effort with
`synapse effort start <slug> --title "..."` (a short lower-case slug from the
task). It creates PLAN.md and EXECUTION.md from the templates and puts this
session on the effort; fill both in. If it prints an `error:` line (invalid
slug, folder exists), fix the argument and run it again; do not fall back.

Only if the `synapse` command is not available (command not found), use
`.claude-work/current/` from the templates (step 2b) and say so once. Start
the files from `${CLAUDE_PLUGIN_ROOT}/templates/PLAN.md` and
`${CLAUDE_PLUGIN_ROOT}/templates/EXECUTION.md`.

## Reset current/ for a new task

An `EXECUTION.md` `## Resume` section from the previous task is replaced or
removed, and a working `NOTES.md` is started fresh only if its last line is
a merge marker or end-session has run.

## Session hooks

Per project, optional.

- Run each command or skill the `## Session hooks` section of `PLAN.md`
  lists before choosing the next step. Typical hooks pull outside state into
  the plan: an issue-tracker or roadmap sync, a CI status check, a
  dependency audit.
- Fold anything new the hooks surface (fresh issues, failing checks, drift)
  into the plan **before** choosing the next step.
