# PLAN — Choreganize

History before 2026-09-22 (v1.2 → v1.7.0 train, sharing re-platform, Edit-tab add-flow, paid tiers) lives in
`.claude-work/archive/PLAN_2026-09-22-1225.md` (+ `EXECUTION_…`, `NOTES_…`). This file was reset for the
AI initiative; only standing rules carried forward.

---

## Standing rules (carried forward)

- **Toolchain:** `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` (stable Xcode 27.0, has the Metal
  toolchain). Never install/remove Xcode or components. Sim: pick a UDID from `xcodebuild -showdestinations`
  (known-good `CZ-Portrait` <sim-udid>). **Never `xcodebuild test` against the
  CG-Share-Owner/Participant rig sims.**
- **Checkout hygiene (user, 2026-09-27):** work in the **main checkout** (`<workspace>/Choreganize`); the
  `.worktrees/` folder was collapsed and removed at the user's request, so it's the folder Xcode builds. Before any
  branch switch: working tree clean + `git diff --name-status <from> <to> --diff-filter=D` shows no files the
  user needs (CGZ2.icon scare). The six untracked Mac listing PNGs at the root stay uncommitted.
- **Ship mechanics:** feature branch → PR into `main`; the user merges; Xcode Cloud builds on merge and assigns
  its own build numbers (ask the user for the last used ASC build before any bump; bump only on a branch that
  contains `main`, across app + widget + `ChoreganizeMac`). PR/stack commands need the user's per-session grant.
  No Claude attribution in commits/PRs.
- **Pricing:** Plus = $4.99/yr + $19.99 lifetime (no monthly). Keep the Terms/Privacy footer in every App
  Store description.
- **Schema:** any new synced Core Data field ⇒ one batched Production CloudKit schema deploy (user step).

---

## 🎯 Current initiative (2026-09-27): 1.9.0 Work view — Quick Add ghost (#127) + One-offs (#128)

Built as **stack #134** (#131 → #132 → #133); progress + next steps in EXECUTION.md. Design, user decisions and the
risk gate: **`PLAN-quick-add-one-offs.md`**. Insights 2.0 (#129) is jotted for a later sprint. The AI initiative
below merged 2026-09-27 (stack #124) and is in App Review as 1.8.0 (21).

---

## 🎯 Current initiative (2026-09-22) — On-device AI: "Snap a room"

**User intent:** use the iOS 27 on-device Apple Foundation Models for **base-experience (free)** features —
the model runs on the device, so it costs nothing per use.

| User idea | Roadmap row | Status in this plan |
|---|---|---|
| **A** — photo of a room → suggest new chores for it, inside the Edit/Add flow | CG-A1 / #105 | **Build first** |
| **B** — photo of a room → check off chores that look done | CG-A3 / #107 | **Build second**, eval-gated |
| **C** — conversational variant of B | none (new) | **Deferred**; B's session design leaves room for it |
| (not requested) NL chore entry / SF-Symbol room glyphs | CG-A2 #106 / CG-A4 #108 | Out of scope; reuse the shared layer later |

### Verified facts (2026-09-22, this Mac, macOS 27.0 build 26A428, Xcode 27.0 SDK)
- iOS/macOS 27 `FoundationModels` takes images: `Attachment(UIImage)` (UIKit overlay), `Attachment(cgImage:)`,
  `Attachment(imageURL:)`, `Attachment(pixelBuffer:)`; `Attachment` is `PromptRepresentable`, so it goes straight
  into a `respond(generating:) { "text"; Attachment(…) }` prompt builder. `ImageReference` is `Generable` (the
  model can point back at a labelled image, for multi-photo prompts).
- `SystemLanguageModel.default` here: `.available`; capabilities **vision ✅ guidedGeneration ✅ toolCalling ✅
  reasoning ❌**; `contextSize` = **8192** tokens. Capability check API: `model.capabilities.contains(.vision)`
  (iOS 27+); `LanguageModelError.unsupportedCapability` otherwise.
- End-to-end image → `@Generable` struct round trip: **0.5–2.3 s** (3000×2000 JPEG; smaller is not slower).
- `tokenCount(for:)` works for text (40 chore lines ≈ **591 tokens**, ~15/chore) but **fails (code -1,
  `ModelManagerServices` 1001) for image prompts** — an OS model-service error, not an Xcode one.
- **Image cost MEASURED anyway: ~131 tokens per photo** (constant for ≥1024 px long edge, landscape or
  portrait, JPEG or PNG; 512 px → 195, 256 px → 67). Method: overflow the context on purpose — the
  `LanguageModelError.contextSizeExceeded` payload reports the request's exact `tokenCount`; filler-only vs
  filler + image → delta. ⇒ the image is ~1.6% of the 8K window; the budget is dominated by text.
- Xcode 27.1 beta / 27.2 beta release notes have **no Foundation Models items**; the "Foundation Models"
  Instruments template (per-request prompts, token usage, latency) already ships in stable Xcode 27.0.
- `PrivateCloudComputeLanguageModel` exists but has **quotas** (`quotaUsage`, `.quotaLimitReached`) + network →
  not "free/unlimited". `_Vision_FoundationModels` only adds `OCRTool`/`BarcodeReaderTool` (not needed).
- CLI probe pattern: `DEVELOPER_DIR=… xcrun swiftc -o probe main.swift` (top-level code, no
  `-parse-as-library`); probes in the session scratchpad `fm/`.
- App reality: `IPHONEOS_DEPLOYMENT_TARGET = 18.0`, Mac 26.0; no camera/photo-picker code and no
  `NSCameraUsageDescription` yet; no FoundationModels code on `main`. The add-flow engine (`AddFlow.swift`:
  `ChoreDraft`/`AreaRef`/`AddFlowCommit` with case-insensitive area dedup) and `recordCompletion(on:by:)` are the
  integration seams. Stale local branch `feature/ai-foundation-models` = old phase-4 head, 0 AI commits.

### Design (proposed — see Decision log for what is settled)
**Shared layer — `RoomVision.swift` (one pure-ish file, compiled by both the app and the Mac eval harness):**
- `AIAvailability` (`@MainActor`, observable): iOS 27+ ∧ `availability == .available` ∧ `.vision` capability ∧
  `supportsLocale()`. Entry points render only when available; otherwise the app is unchanged.
- Image prep: downscale to ≤1024 px long edge, keep orientation, in memory only. **Photos are never saved,
  synced, or sent anywhere.**
- `@Generable` output types + `Instructions` text + **pure mappers** (model output → `ChoreDraft` / completion
  candidates) — the mappers are unit-testable without the model.
- Errors: guardrail violation, context overflow, model not ready → one friendly "Couldn't read this photo"
  state + retry; never a crash, never partial writes.

**A — "Snap a room" (Edit tab, CG-A1):**
- Third lens card in `EditHomeView` (shown only when available) → camera (device) / `PhotosPicker` (sim, Mac,
  or no camera) → "Looking at your room…" → room name (matched to an existing area when names agree, else
  `AreaRef.new`) + 5–10 suggested chores with cadence (daily/weekly/monthly/yearly), existing chores in that
  area passed in and filtered out → drafts land in the **existing editable Review step** → `AddFlowCommit`.
- Output type sketch: `RoomSuggestion { roomName; chores: [SuggestedChore { name; cadence enum; why }] }`
  with `@Guide` count limits.

**B — "Check off from a photo" (Work tab, CG-A3):**
- Entry on **today's** day page → pick the room (default: last used / inferred) → photo → the model gets only
  that room's **due-and-open chores today** (`Scheduling.chores(_:for:)`, not completed) → per chore:
  `looksDone | notDone | cantTell` + short reason. Chore references are **constrained by a dynamic generation
  schema** (enum of the real candidate names) so the model can't invent chores.
- Results sheet: "Looks done" pre-checked, "Can't tell"/"Not done" unchecked → user confirms →
  `recordCompletion(on: today)` (household attribution comes for free). **Never auto-completes.**
- Keep the `LanguageModelSession` alive for the sheet → a later follow-up turn ("I also did the dishes") is
  the natural hook for C.

### Risks
1. **B accuracy / trust** (roadmap flagged it experimental): many chores aren't visible in a photo (trash out,
   plants watered). Mitigation: tri-state output, confirm-first, eval gate on real photos before any UI.
2. **Device reach:** only iOS 27 + Apple-Intelligence-capable + enabled devices get it — "free" but not
   universal. The manual wizard stays the baseline.
3. **Context budget (8K):** retired — photo ≈131 tokens, a room's ~20 candidate chores ≈300. Keep a soft cap
   (~40 chores/room) and handle `contextSizeExceeded` gracefully anyway.
4. **Simulator:** unknown whether the iOS 27 sim runs the model on this host (likely, since the Mac has Apple
   Intelligence) — camera never works in the sim → `PhotosPicker` path doubles as the test path.

---

## Decision log

- (2026-09-27) **1.9.0 stack #134 built** off main 177ddf4. Durable calls:
  - Ghost = a fixed 42 pt footer slot per section. On iOS it widens to the card and eats the footer's own padding,
    and section spacing is 0 on days that offer it, so the resting cost is ~30 pt/section. The Mac clips footer
    overflow, so it keeps the padding.
  - One-offs lead each upcoming day's list and take the date header. Completing = delete after a 1.5 s grace.
  - Three look choices were left to the user as DEBUG A/Bs (ghost look, one-off tint, in-list vs shelf) on a
    review artifact. Remove the losing variants before the stack merges.
  - The additive model edit was verified against a real 1.8 on-disk store.
  - Still owed before Production: the old-client rig gate.

- (2026-09-26, night) **#106 built as PR #130** (top of stack #124, 7 PRs). **Reusable insight for the
  on-device model:** don't ask a 3B model for numbers or lists it has to infer. Asking for days and "every N"
  made it echo digits from the prompt, and asking it to quote each chore's words made it echo greetings as
  chores. What worked: have it **copy spans** (the words that say when and where), **read them with plain
  code**, and **ground every output in the input text** (drop chores, times and rooms the text doesn't
  contain). Eval went 30/36 → 41/41 + 15/15 held-out, 0 invented. Rooms are now only ones the chore's own
  clause names (no implied "Kitchen").
- (2026-09-26, later) **#106 AI natural-language entry joins the AI sprint for 1.8.0** (user: "feels great with
  the photo suite"; they'll market 1.8.0 as the big AI release). It's built as **"Describe Chores"**:
  - An Edit-tab entry next to Snap a Room (the Mac gets a two-column sheet).
  - Type or dictate one or many chores; the on-device model returns name, cadence, days, "every N" and room.
  - The results go into the same review → `AddFlowCommit` path.
  - Tier = **Free**, like the photo suite (the Msg-1 rule that on-device costs nothing). The user didn't state it;
    flagged to confirm.
  - iOS/macOS 27 only, like the rest of the suite, so every device runs the model tuned in the eval harness.
  - Plus-only schedule parts (every N > 1, several days) apply for Plus; free users get the plain schedule with
    a note.
  - Quick Add + One-offs move to **1.9.0**. One-offs decisions (assigning = Plus, household-synced limit, in-list
    placement with an optional DEBUG shelf A/B) are in `PLAN-quick-add-one-offs.md`.
- (2026-09-26) **Roadmap cleanup (user-requested).** v1.7.0 has been live since 2026-09-22 (public App Store
  lookup), so the 14 issues it shipped are closed as completed: #59, #62, #64, #94 (spike, verdict shipped as #64)
  and #95–#104. Each has a "Shipped in v1.7.0 (iOS build 20) … via PR #110/#111/#112 (stack #114) and #115"
  comment, matching the v1.6.0 convention. CSV Status and board Design Status now read "Shipped — vX (date)" for
  those rows and for the v1.6.0 rows (#82, #85–#93), which still said "Not started". The board is Done for all 24.
  Filed CG-26/#127 (Quick Add ghost), CG-27/#128 (One-offs) and CG-28/#129 (Insights 2.0, jotted).
  **Next sprint = #127 + #128** (`PLAN-quick-add-one-offs.md`). Key calls:
  - The ghost lives in a fixed slot under every section, so no row ever moves.
  - One-offs are a new `CDOneOff` entity, not a chore flag, so 1.7.0 clients ignore them and stats exclude them
    by construction.
  - Five open questions are listed there.
- (2026-09-26) **Debug/production data fence (#123) before any Mac local runs** (user rule: Mac dev runs had merged
  CloudKit Development data into production). Debug builds never open the production store (Development/Isolated folders,
  mode-suffixed pref keys); isolated mode = CloudKit off. AI stack rebased on it (stack #124) so device builds are safe.
  **Mac photo features designed Mac-first** (#121 comment): photos come in by drop/paste/Continuity Camera/Photos/Open, two-
  column sheets, room pop-up with model room identification; entry points = Edit row, Work toolbar, drops, File menu
  (⌥⌘N, ⇧⌘K). **Mac Settings (#122)**: every pane a grouped form at 560 pt, per-pane height, shared iOS views render Mac
  controls/copy under `#if os(macOS)`; `PlatformText.plusLocation`.
- (2026-09-26) **Built + shipped to review as GitHub stack #119** (#117 engine+eval → #118 Snap a Room → #120 photo
  check-off), all drafts, worktree `.worktrees/choreganize-ai`. Durable facts: the **iOS 27 Simulator runs the on-device
  model with vision** (real-inference UI tests work there, ~20–35 s each); FoundationModels auto weak-links (Debug + Release,
  minos 18.0); DEBUG `CHOREGANIZE_ROOM_PHOTO` = test-photo hook for both flows; eval harness `tools/fm-eval/run.sh`.
  Prompt lessons (see #117 table): no concrete example lists (they leak), no "don't answer not_done" wording (halo →
  false done), per-chore `visible` flag. Entry points are iOS-only; Mac = fast follow. Photos never stored.
- (2026-09-22) **AI initiative scoped.** User wants on-device Foundation Models features in the **free base
  experience** (flips roadmap Tier for CG-A1/#105 and CG-A3/#107 from Plus → Free). Order **A → B**, **C
  deferred**. Verified on this Mac that the on-device system model is vision-capable with guided generation
  (facts above) — the July "BLOCKED - AI tooling not stable" status on #105–#108 is obsolete.
  **Architecture (agent-recommended, settled unless the user objects):** on-device `SystemLanguageModel` only,
  never PCC (quotas + network); keep iOS 18 min target with runtime gating; photos in-memory only; one shared
  `RoomVision.swift` also compiled into a Mac eval harness so prompts are tuned against real photos before any
  UI is built; B is suggest-and-confirm with tri-state output.
- (2026-09-22) **GitHub updated for the free tier (user-requested):** #105 + #107 bodies (Tier: Free, entitlement
  n/a, dated note), board Tier → Free + Entitlement Scope → n/a, CSV CG-A1/CG-A3 likewise (#107 dropped the
  "Plus / experimental" tier; "experimental" stays in its title). Not changed: #106 (still Plus), the BLOCKED
  design status on #105–#108, no row for C yet.
- (2026-09-22) **Stay on stable Xcode 27.0** — the betas add nothing for Foundation Models, and the image
  `tokenCount` bug lives in the OS service. **Single-call, image-direct prompts (no image→text stage).** The
  token budget doesn't need it (photo ≈131 tokens); a text intermediate loses the details B needs because it's
  written before the model knows which chores matter; storing room descriptions would be new personal data
  (CloudKit sync, schema deploy, privacy label). The inspectability benefit is kept inside one call: declare an
  `observations` property **first** in each `@Generable` output (guided generation fills properties in
  declaration order ⇒ "look, then judge"), and log it in the eval harness. The harness can A/B a two-stage
  variant if a quality problem ever points that way.
