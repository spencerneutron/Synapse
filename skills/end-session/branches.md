# Branch details for end-session

Read the section whose condition `SKILL.md` names. Steps 3 to 6 of `SKILL.md`
then apply as written.

## Closing or pausing an effort

When the session is on an effort **and the user says that effort is finished**, run this in place of `synapse archive`:

```
synapse effort done <slug> --json
```

It archives the effort and closes it. Its JSON has the same keys as `synapse archive` (`session_id`, `copied`, `missing`, `notes_path`) plus `folder`, the effort's folder: use `folder` for the working files in steps 3, 4 and 6 (the scan and the merge marker in `NOTES.md`), and `session_id` (the archive ID) for everything else. `done` copies an unmerged working `NOTES.md` as `NOTES_<id>.md`; step 4 then writes the fuller notes over that copy. Never run `done` without the user's word.

For an effort that continues, run `synapse archive` as `SKILL.md` says; the effort stays open. If its true state is waiting or parked, say so with `synapse effort wait <slug> --on "..."` or `synapse effort park <slug>`.

## Recommend extraction

Step 5b, when `accept` is `review` or the user declined extraction: recommend, do not run.

> "Archive complete. Recommend running `/synapse:extract-session 2026-04-23-1645`
> to promote this session's decisions and patterns into the vault and
> embed it for recall. Skip if this was a throwaway session or if
> `synapse vault verify` fails."
