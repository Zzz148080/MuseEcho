# 可信结果页呈现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve MuseEcho's established result-page and five-track timeline layout while showing only music facts and controls that are useful and supportable.

**Architecture:** Presentation-only filtering lives in the React feature layer. The backend keeps storing its immutable deterministic output; the frontend filters non-user-facing structure cluster labels and unusable chord events before rendering. Existing timeline selection remains independent of chord candidates.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, existing CSS token system.

## Global Constraints

- Do not add dependencies, API fields, or re-run audio analysis in the browser.
- Preserve current waveform, energy, event, playhead, pointer drag, keyboard seek, and start/end selection behavior.
- Do not render internal A/B/C structure cluster labels, `unknown` chord blocks, text event list, question panel, algorithm identifiers, task IDs, or lifecycle copy in the completed workspace.
- All user-facing music claims must originate from existing persisted result data and pass the existing confidence threshold.

---

### Task 1: Filter map events and expose concise empty states

**Files:**
- Modify: `frontend/src/features/timeline/Timeline.tsx`
- Modify: `frontend/src/features/timeline/Timeline.test.tsx`

**Interfaces:**
- Consumes: `AnalysisResult.sections`, `AnalysisResult.chords`, `isUsableConfidence()`.
- Produces: the same five track elements and selection controls, with only usable chord events visible and no structure cluster label output.

- [x] **Step 1: Write failing component tests**

Add assertions to the rich fixture that labels `A` and low-confidence/`unknown` chords do not render in the map or accessible text, while the known `G` candidate remains a button. Add an assertion that the old text event list and its summary are absent.

- [x] **Step 2: Run tests to verify RED**

Run: `vitest run src/features/timeline/Timeline.test.tsx`

Expected: FAIL because the existing map renders section labels, unknown chord blocks, text event list, and implementation-oriented selection text.

- [x] **Step 3: Implement minimal filtering and copy**

Use local filtered arrays. Preserve all SVG and track layout markup. Replace the section event strip with an empty-state label when there are no stable user-facing sections; render chord buttons only for usable non-unknown events; remove `<details className="timeline__event-list">`; keep selection controls but use concise “选择片段以回听和比较” copy.

- [x] **Step 4: Run focused GREEN tests**

Run: `vitest run src/features/timeline/Timeline.test.tsx`

Expected: PASS with existing seek/selection behavior unchanged.

- [ ] **Step 5: Commit**

Commit message: `fix: show only usable music events on timeline`

### Task 2: Simplify Music DNA and teach only needed chord notation

**Files:**
- Modify: `frontend/src/features/dna/MusicDNA.tsx`
- Modify: `frontend/src/features/dna/MusicDNA.test.tsx`
- Modify: `frontend/src/features/chords/ChordDetails.tsx`
- Modify: `frontend/src/features/chords/ChordDetails.test.tsx`

**Interfaces:**
- Consumes: `TrackResult`, `ChordResult`, existing theory fields.
- Produces: concise current facts and selected-candidate details without implementation copy.

- [x] **Step 1: Write failing component tests**

Assert that Music DNA no longer exposes source kind or counts of structure/chord events, and that unavailable key is labelled “暂未判定”. Assert the chord detail supplies a compact notation guide and does not show `deterministic-triad-theory-v1`.

- [x] **Step 2: Run tests to verify RED**

Run: `vitest run src/features/dna/MusicDNA.test.tsx src/features/chords/ChordDetails.test.tsx`

Expected: FAIL because existing components expose source/summary counts and algorithm identifiers.

- [x] **Step 3: Implement minimal component changes**

Keep time, usable BPM, key state, beat count and energy. Remove source and structure/chord count facts. In chord details, replace algorithm/limitation copy with one concise notation guide and retain only persisted music facts.

- [x] **Step 4: Run focused GREEN tests**

Run: `vitest run src/features/dna/MusicDNA.test.tsx src/features/chords/ChordDetails.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: simplify music result facts`

### Task 3: Hide question-and-answer from the completed workspace

**Files:**
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.tsx`
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: already-loaded result and deletion panel.
- Produces: completed workspace with player, DNA, timeline, chord detail, and retention only.

- [x] **Step 1: Write a failing workspace test**

Assert that a loaded workspace does not contain the “片段问答” heading or question textarea, while the retention/delete interaction remains available.

- [x] **Step 2: Run test to verify RED**

Run: `vitest run src/features/workspace/AnalysisWorkspace.test.tsx`

Expected: FAIL because `QuestionPanel` currently renders.

- [x] **Step 3: Remove only the inactive UI integration**

Remove `QuestionPanel`, explanation transport wiring and query selection callback from `AnalysisWorkspace`; retain `useTimeline` for player/timeline synchronization. Remove now-unused support-grid CSS only if it has no remaining consumer; do not delete the QuestionPanel feature/API code.

- [x] **Step 4: Run focused GREEN tests**

Run: `vitest run src/features/workspace/AnalysisWorkspace.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: focus completed workspace on listening`

### Task 4: Verify visual and live behavior

**Files:**
- Modify: `docs/superpowers/specs/2026-08-14-trustworthy-result-presentation-design.md`

- [x] **Step 1: Run related frontend suite and build**

Run the four feature test files, typecheck, and production build using only existing lockfile dependencies.

- [x] **Step 2: Rebuild local development services**

Build the existing app/gateway profiles without changing lockfiles or downloading new tools.

- [ ] **Step 3: Exercise retained real result in Edge**

Verify the screenshot baseline layout remains: player/Music DNA overview, original five-track map, selection sliders, and a clickable A# candidate. Verify no A/B/C section labels, unknown chord blocks, text event list, or question panel are visible.

Controller note: on 2026-08-14 the real Edge page selected `C:\Users\P\Downloads\《江南烟水》随性的木鱼-流行.mp3` and accepted both consent controls, but its controlled-upload request stopped before reaching the gateway. The same file was accepted through the same local HTTPS gateway as analysis `f12fa6ca-66a2-4e16-9b4c-2ed078759679`, which completed without an error. The post-analysis visual pass remains pending a browser session whose upload channel is available.

- [ ] **Step 4: Commit and push**

Commit message: `feat: refine trustworthy music results`; push the dedicated branch after verification.
