# EXECUTION — 1.9.0 Work view: Quick Add ghost (#127) + One-offs (#128) [ACTIVE] (2026-09-27)

Previous EXECUTION (AI initiative, stack #124, merged 2026-09-27 as 1.8.0 (21), in App Review) archived
byte-identical as `.claude-work/archive/EXECUTION_2026-09-27-2251.md`. Design + user decisions:
`PLAN-quick-add-one-offs.md`. Standing rules: PLAN.md.

**Stack #134** (main checkout `<workspace>/Choreganize`, gh-stack local tracking inited):
`main` ← **#131** `feature/quick-add-ghost` (00777c0) ← **#132** `feature/one-offs-model` (5fc8f90) ←
**#133** `feature/one-offs-shelf` (aa82660). Not drafts. No version bump yet (still 1.8.0 (21)).
**Review page (user):** <review page link> — three look decisions with screenshots +
a 30 s recording. Review assets: scratchpad `review/` (session-local).

## Progress log (2026-09-27)
- Branched off `main` 177ddf4 (stack #124 merged). Checkout switched from `feature/ai-describe-chores` (no deletions).
- **#131 Quick Add ghost.** Footer slot per section (42 pt; iOS: `-16` horizontal / `-6` vertical padding so it spans
  the card and reuses the footer's padding; `listSectionSpacing(.custom(0))` on days that offer it) ⇒ ~30 pt/section at
  rest on iOS, more on the Mac (its footer clips overflow, so no negative vertical padding there). `QuickAddTracker`
  (@Observable; frames `@ObservationIgnored`). Body probe: today's `DayPage.body` ran 9× over a full scroll+add UI test
  (no per-frame work). `onScrollPhaseChange` works on `List` (iOS 27). Three DEBUG looks (dashed default / glass / soft).
- **#132 model.** `CDOneOff` + `CDHousehold.oneOffs` + `oneOffsUnlimited`. Migration verified: main's 1.8 build seeded
  a persistent local-only store on CZ-Portrait (13 chores / 29 completions), then this build opened it intact with
  `ZCDONEOFF` + `ZONEOFFSUNLIMITED` added (app uninstalled from CZ-Portrait afterwards).
- **#133 UI.** In-list first section (date header moves onto it), round checkbox → 1.5 s grace → poof → delete;
  Chore | One-off switch in the ghost's sheet; section ＋; Mac ⇧⌘N; limit toggle in Hub + Mac Settings (household-synced);
  `AssigneeSection` extracted. DEBUG A/B: `-oneOffPlacement shelf` (via `.safeAreaInset(edge: .top)`), `-oneOffLook note`.
- **Tests:** 236 unit (QuickAddTests, OneOffTests new); UI: QuickAddUITests ×2, OneOffUITests ×3, add-flow regression,
  `testCaptureQuickAddAndOneOffs` (screenshots). iOS + Mac Release builds OK. Mac checked via isolated store capture
  (`CHOREGANIZE_QUICKADD_HOLD=1`, `CHOREGANIZE_SEED_ONE_OFFS`).
- **Roadmap:** CSV CG-26/27 → "In review — stack #134"; the 1.8.0 rows (A1/A2/A3/A5/25) → "Merged … in App Review as
  v1.8.0 (21)"; board #128 → In Progress; Design Status pushed for all seven. #106 auto-closed on #130's merge.
- Lessons: `.accessibilityHidden` doesn't remove a view from the XCUI tree (the ghost is conditionally inserted instead);
  an `.accessibilityIdentifier` on a List row's HStack hides the inner Button's identifier; offscreen day pages are
  mounted, so UI tests pick the hittable match.

- **Review outcome (user, 2026-09-27):** defaults kept (dashed ghost, accent tint, in-list), but the ghost was "a bit
  anemic" beside real rows → now **58 pt on iOS** (rows ≈74 pt) with explicit body/caption fonts (the footer
  otherwise shrinks them); Mac stays 42 pt. Resting cost ≈45 pt/section on iOS. Variants + Hub pickers removed:
  00777c0 on #131, aa82660 on #133; `gh stack rebase --upstack --no-trunk` (conflicts in SettingsKeys/HubView;
  `compatCardBackground` moved up to #133) + `gh stack push` (force-with-lease). PR bodies updated. 236 unit + 6 UI
  tests green; iOS + Mac Release OK. Review page republished (v2) with before/after.

## Next
1. [x] Look decisions made and variants removed (see above).
2. [ ] **Rig gate (needs the user present — sandbox sims sign-in):** participant `<participant-sim>` on a main (1.8) build, owner
   `<owner-sim>` on #133; owner adds household one-offs (needs a DEBUG household seed hook or manual taps — no XCUI on rig
   sims); participant must not crash or stall sync (stream logs live). Never install an older build over a store that
   has run the new model.
3. [ ] `/deploy public 1.9.0 build <ask>` on top of #133 (update the deploy skill's iOS test list with
   `testCaptureQuickAddAndOneOffs`; Mac store capture can take `CHOREGANIZE_SEED_ONE_OFFS`).
4. [ ] **User:** CloudKit Production schema deploy (`CD_CDOneOff`, `CD_oneOffsUnlimited`) before 1.9.0 ships; merge #134.
5. [ ] Close #127/#128 with the ship comment when 1.9.0 is live (they auto-close on merge via "Closes").
