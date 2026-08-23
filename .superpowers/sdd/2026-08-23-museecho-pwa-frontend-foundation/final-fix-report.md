# MuseEcho frontend foundation final fix report

Date: 2026-08-24 (Asia/Shanghai)

Reviewed base: `26c5907`

Implementation commit: `6bb780f` (`fix: preserve accessible chord detail state`)

Authoritative design: `docs/superpowers/specs/2026-08-23-museecho-pwa-frontend-optimization-design.md`

## Status and scope

All four Important findings are implemented together in the frontend foundation. The change is limited to React presentation state, responsive accessibility, timeline chord presentation, shared confidence filtering, CSS, and frontend/E2E tests. It does not change backend/API/Python/ML/model/dataset/deployment behavior and adds no runtime dependency.

The implementation still creates one `useTimeline(...)` controller and one `AudioPlayer` inside `LoadedWorkspace`. Overview/map/deep navigation continues to conditionally replace only the view content, so the same `<audio>` media element and shared timeline state remain mounted.

## Finding 1 — selection identity was coupled to detail visibility

### Root cause

`selectedChord` was the sole condition for both `aria-pressed` and detail rendering. `closeChord()` and every navigation away from the map set it to `null`, so presentation-only close/navigation destroyed the domain selection.

### Focused TDD evidence

Tests changed/added in `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`:

- `switches views without refetching and opens chord theory as a returnable detail`
- `preserves selection across view navigation and restores focus only to a freshly opened trigger`
- `clears the preserved chord only through an explicit deselection action`
- `clears workspace selection state when the analysis identity changes`

Initial RED command:

```text
npm test -- src/features/workspace/AnalysisWorkspace.test.tsx src/features/timeline/Timeline.test.tsx src/features/workspace/AnalysisFeatureHub.test.tsx
```

Expected RED result:

```text
Test Files  3 failed (3)
Tests       6 failed | 15 passed (21)
```

The close/navigation cases failed because the return control did not receive focus and the selected chord changed from `aria-pressed="true"` to `false`. The explicit-deselect test was also run separately before implementation and failed at the preserved-selection assertion:

```text
Test Files  1 failed (1)
Tests       1 failed | 7 skipped (8)
Expected aria-pressed="true"; received aria-pressed="false"
```

Self-review found the cached-analysis edge case before completion. Its independent RED run was:

```text
npm test -- src/features/workspace/AnalysisWorkspace.test.tsx -t "analysis identity changes"
Test Files  1 failed (1)
Tests       1 failed | 8 skipped (9)
```

It failed because the old `清除和弦选择` control remained after a cached `analysisId` change.

Final focused GREEN command:

```text
npm test -- src/features/workspace/AnalysisWorkspace.test.tsx src/features/timeline/Timeline.test.tsx src/features/workspace/AnalysisFeatureHub.test.tsx
Test Files  3 passed (3)
Tests       23 passed (23)
```

### Implementation evidence

- `AnalysisWorkspace.tsx:87` adds `detailOpen` independently from `selectedChord`.
- `closeChord()` changes only `detailOpen`; view changes close presentation without clearing the chord.
- `clearChord()` is the explicit deselection path exposed as `清除和弦选择` by `Timeline`.
- `Timeline.tsx:193` and `Timeline.tsx:255` compare chord IDs for stable `aria-pressed` selection instead of object reference equality.
- `AnalysisWorkspace.tsx:62` keys `LoadedWorkspace` by `analysis_id`, clearing all workspace selection state when the analysis actually changes, including a cached-result transition.

### Files changed for this finding

- `frontend/src/features/workspace/AnalysisWorkspace.tsx`
- `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- `frontend/src/features/timeline/Timeline.tsx`
- `frontend/src/features/timeline/Timeline.test.tsx`

## Finding 2 — detail did not receive focus and mobile overlay was not modal

### Root cause

Opening a chord only set React state. The mobile CSS made the inline `aside` cover the viewport, but the active element remained on the visually obscured chord and the rest of the application remained keyboard reachable. The same markup also had no way to distinguish mobile modal/subpage semantics from the desktop/tablet side panel.

### Focused TDD evidence

Tests added in `AnalysisWorkspace.test.tsx`:

- `uses a focused modal detail and makes the covered workspace inert only on mobile`
- `keeps the desktop side detail non-modal while moving focus into it`
- the remounted-trigger test above verifies that return focus uses the current visible trigger.

The initial integrated RED could not find a `dialog` and showed that focus remained on the chord. A second independent RED hardened the obscured-root boundary by wrapping the workspace in `.app-shell`:

```text
npm test -- src/features/workspace/AnalysisWorkspace.test.tsx -t "uses a focused modal detail"
Test Files  1 failed (1)
Tests       1 failed | 7 skipped (8)
Expected .app-shell to have inert; received null
```

The final focused GREEN result is the 23/23 run recorded above.

### Implementation evidence

- A breakpoint-aware `useMediaQuery` hook uses the same `(max-width: 599px)` boundary as CSS.
- Opening or changing a detail focuses its return button.
- Mobile renders the detail through a body portal as `role="dialog"`, `aria-modal="true"`, labelled by the chord heading.
- While that portal is open, the closest `.app-shell` (or standalone workspace fallback in component tests) receives both `inert` and `aria-hidden="true"`; body scrolling is locked. The portal is outside that inert subtree.
- Desktop/tablet keeps the inline implicit `complementary` side panel with `aria-label="当前和弦详情"` and does not emit dialog or modal semantics.
- Close restoration is explicitly requested only by the detail return action and checks `trigger.isConnected`. Navigating away cancels restoration. A later fresh open always replaces the stored trigger with the currently visible chord button.

### Files changed for this finding

- `frontend/src/hooks/useMediaQuery.ts`
- `frontend/src/features/workspace/AnalysisWorkspace.tsx`
- `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- `frontend/src/styles/global.css`
- `e2e/responsive.spec.ts`

## Finding 3 — short absolute chord controls were not a viable mobile touch path

### Root cause

Every usable chord was an absolutely positioned timeline button whose width equalled its duration percentage. Very short chords could therefore be approximately 1px wide, and the track height left controls below the recommended 44px touch dimension. Enlarging those absolute controls would overlap adjacent events and make event identity dishonest.

### Focused TDD evidence

Test added in `frontend/src/features/timeline/Timeline.test.tsx`:

- `offers mobile chord events as chronological non-overlapping 44px controls`

The production mutation it catches is removal of the mobile static event list or reintroduction of absolute-positioned chord buttons as the mobile controls. Its RED failure was:

```text
Unable to find an accessible element with role "region" and name "和弦事件列表"
```

The test also independently asserts chronological literal accessible names, selection state, real click behavior, and the absence of `button.timeline__event--chord` controls on mobile. It is GREEN in the final 23/23 focused run.

`e2e/responsive.spec.ts` now additionally measures the mobile chord control at 390px and 320px and requires both width and height to be at least 44 CSS pixels, alongside the existing page-overflow checks.

### Implementation evidence

- Usable chords are sorted by start time, end time, then ID for deterministic chronological reading order.
- At the mobile breakpoint the absolute track keeps noninteractive, `aria-hidden` visual spans only.
- A separate semantic `和弦事件列表` uses ordinary document-flow buttons with honest symbol, start/end, and confidence names.
- `.timeline__chord-list-button` has `width: 100%`, `min-width: 0`, `min-height: 2.75rem` (44px at the root 16px size), and wrapping secondary text.
- No absolute target is widened, so adjacent events cannot overlap; list layout and `overflow-wrap: anywhere` avoid page-level horizontal overflow.

### Files changed for this finding

- `frontend/src/hooks/useMediaQuery.ts`
- `frontend/src/features/timeline/Timeline.tsx`
- `frontend/src/features/timeline/Timeline.test.tsx`
- `frontend/src/styles/global.css`
- `e2e/responsive.spec.ts`

## Finding 4 — deep summary counted candidates the map filtered out

### Root cause

`AnalysisFeatureHub` checked only `symbol !== 'unknown'`, whereas `Timeline` additionally applied the shared confidence gate. A non-unknown low-confidence chord therefore increased the summary without appearing in the map.

### Focused TDD evidence

Test added in `frontend/src/features/workspace/AnalysisFeatureHub.test.tsx`:

- `excludes low-confidence chords from the visible candidate count`

RED result from the integrated run:

```text
Unable to find "1 个可见候选"; rendered "2 个可见候选"
```

The regression is GREEN in the final 23/23 focused run.

### Implementation evidence

- `confidence.ts:16` defines `isVisibleChordCandidate`, combining the unknown-symbol check with the existing `isUsableConfidence` predicate.
- `Timeline.tsx:34` and `AnalysisFeatureHub.tsx:22` both filter with that same function, eliminating duplicated eligibility logic.

### Files changed for this finding

- `frontend/src/features/confidence.ts`
- `frontend/src/features/timeline/Timeline.tsx`
- `frontend/src/features/workspace/AnalysisFeatureHub.tsx`
- `frontend/src/features/workspace/AnalysisFeatureHub.test.tsx`

## Full verification

All commands below were run on the final implementation tree at commit `6bb780f` (the report itself is a later documentation-only change).

| Check | Command | Result |
| --- | --- | --- |
| Focused regressions | `npm test -- src/features/workspace/AnalysisWorkspace.test.tsx src/features/timeline/Timeline.test.tsx src/features/workspace/AnalysisFeatureHub.test.tsx` from `frontend` | PASS: 3 files, 23 tests |
| Full frontend suite | `npm test` from `frontend` | PASS: 16 files, 104 tests |
| Frontend TypeScript | `npm run typecheck` from `frontend` | PASS, exit 0 |
| E2E TypeScript | `npm run typecheck` from repository root | PASS, exit 0 |
| Production build | `npm run build` from `frontend` | PASS: 100 modules transformed, Vite build exit 0 |
| Diff hygiene | `git diff --check` | PASS, exit 0; Git emitted only the repository's LF→CRLF checkout warnings |

## E2E execution and environment concern

The browser suite did not reach an assertion in this local environment. This is recorded as an environment limitation, not presented as a pass and not hidden with a backend/test bypass.

Environment evidence:

```text
node v24.16.0        (authoritative/package target is Node 22.22.2)
npm 11.13.0         (packageManager declares npm 10.9.8)
ffmpeg=False
ffprobe=False
```

Attempts:

1. `npm run e2e` built the frontend successfully, then global setup failed with `spawn python ENOENT`.
2. Setting `MUSEECHO_E2E_PYTHON=C:\WINDOWS\py.exe` built successfully, but the Windows launcher itself was configured to the missing `D:\python\python.exe` and exited 101 before server health.

Therefore this wave could not re-observe the supplied known upload 503 caused by absent ffmpeg/ffprobe; it stopped earlier because no usable Python interpreter exists. No claim is made that the E2E assertions or the updated 320px/390px measurements ran. The supplied environment contract still predicts an honest upload 503 once the server can start because both ffmpeg executables are absent. Per instruction, the backend and upload behavior were not changed and the E2E was not repeatedly retried.

## Complete files changed

- `.superpowers/sdd/2026-08-23-museecho-pwa-frontend-foundation/final-fix-report.md`
- `e2e/responsive.spec.ts`
- `frontend/src/features/confidence.ts`
- `frontend/src/features/timeline/Timeline.test.tsx`
- `frontend/src/features/timeline/Timeline.tsx`
- `frontend/src/features/workspace/AnalysisFeatureHub.test.tsx`
- `frontend/src/features/workspace/AnalysisFeatureHub.tsx`
- `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- `frontend/src/features/workspace/AnalysisWorkspace.tsx`
- `frontend/src/hooks/useMediaQuery.ts`
- `frontend/src/styles/global.css`

## Self-review

- Re-read all four findings and the design sections covering preserved UI state, mobile full-screen detail, focus restoration, modal/background traversal, 44px targets, accessible chart alternatives, and confidence honesty.
- Confirmed one `useTimeline(...)`, one `AudioPlayer`, and one underlying `<audio>` remain; no alternate player/timeline state was introduced.
- Confirmed close/navigation do not clear the selected chord, explicit deselect does, and cached analysis identity changes remount `LoadedWorkspace` and clear it.
- Confirmed mobile background inerting covers the full `.app-shell`, including the `新的分析` header control, while the portalled dialog remains operable.
- Confirmed desktop/tablet does not claim modal semantics.
- Confirmed mobile track segments are no longer controls; only normal-flow list buttons form the mobile touch path, so widening cannot overlap absolute neighbors.
- Confirmed both visible count and map use `isVisibleChordCandidate`, which delegates confidence eligibility to `isUsableConfidence`.
- Confirmed the implementation commit changes only the authorized frontend/E2E surface and adds no dependency or backend change.

## Remaining concerns

- Browser-level responsive/focus assertions remain unexecuted locally because global setup lacks a usable Python interpreter; once the prescribed Node 22.22.2/Python 3.12/ffmpeg/ffprobe toolchain is restored, run `npm run e2e` without bypasses.
- The current working machine's Node/npm versions differ from the repository's authoritative versions, although unit, type, and production build checks pass under the local versions recorded above.
