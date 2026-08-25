# MuseEcho PWA Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first approved MuseEcho frontend slice: a light Morandi design foundation, compact upload experience, responsive application shell, and progressively disclosed result workspace without changing backend or ML contracts.

**Architecture:** Keep `AnalysisPage` as the upload/status lifecycle owner and keep React Query plus the existing timeline controller as the only data sources. Add a presentation-only `AppHeader`, a local `WorkspaceView` state with three result views, and an honest deep-analysis summary derived entirely from the existing `AnalysisResult`. CSS media queries turn the same semantic structure into desktop side navigation, tablet top navigation, and mobile bottom navigation; no router or runtime dependency is added.

**Tech Stack:** React 19, TypeScript 5.7, Vite 6, TanStack React Query 5, CSS custom properties, Vitest, Testing Library, Playwright

**Spec:** `docs/superpowers/specs/2026-08-23-museecho-pwa-frontend-optimization-design.md`

## Global Constraints

- Do not modify backend API routes, request/response types, Python analysis code, `ml/`, model files, training configuration, datasets, or evaluation logic.
- Do not add a routing library, animation library, component library, icon library, or PWA runtime dependency in this slice.
- Continue to show only real backend state and persisted analysis data; never add sample analysis claims or timer-generated progress.
- Keep upload consent, encrypted-retention copy, deletion, expiry, unknown evidence, and access behavior intact.
- Preserve the existing `AnalysisResult`, `AnalysisStatus`, React Query keys, and shared `TimelineController` interfaces except for an optional presentation callback argument inside the frontend.
- Keep every control keyboard operable, maintain visible focus, satisfy applicable WCAG 2.1 AA contrast, and preserve the existing `prefers-reduced-motion` override.
- The PWA manifest, service worker, install prompt, offline shell, advanced player motion, and mobile mini-player are intentionally deferred to later plans after this foundation passes its tests.
- Use Node `>=22.22.2 <23` for authoritative frontend and E2E verification, as pinned by the repository.

---

## File Structure

### Create

- `frontend/src/styles/tokens.test.ts` — exact palette and contrast contract for the approved Morandi tokens.
- `frontend/src/components/AppHeader.tsx` — brand header and active-analysis “新的分析” action.
- `frontend/src/components/AppHeader.test.tsx` — accessible header behavior.
- `frontend/src/features/workspace/WorkspaceNavigation.tsx` — typed three-view result navigation.
- `frontend/src/features/workspace/WorkspaceNavigation.test.tsx` — navigation labels, selection, and callbacks.
- `frontend/src/features/workspace/AnalysisFeatureHub.tsx` — honest deep-analysis summaries derived from `AnalysisResult`.
- `frontend/src/features/workspace/AnalysisFeatureHub.test.tsx` — real/unknown summary behavior and map handoff.

### Modify

- `frontend/src/styles/tokens.css` — approved light Morandi semantic tokens and application spacing.
- `frontend/src/styles/global.css` — application shell, compact landing view, responsive result navigation, view transitions, and detail treatment.
- `frontend/src/pages/AnalysisPage.tsx` — use `AppHeader`, remove the result-page hero, and keep “start another” at app-shell level.
- `frontend/src/pages/AnalysisPage.test.tsx` — landing/result hierarchy and header action tests; retain URL, deletion, accessibility, and contrast coverage.
- `frontend/src/features/upload/UploadForm.tsx` — concise always-visible limits plus expandable detailed guidance.
- `frontend/src/features/upload/UploadForm.test.tsx` — disclosure behavior while preserving all validation and consent tests.
- `frontend/src/features/timeline/Timeline.tsx` — expose the clicked chord button to the optional selection callback and mark the selected chord.
- `frontend/src/features/timeline/Timeline.test.tsx` — selected chord state and callback trigger coverage.
- `frontend/src/features/workspace/AnalysisWorkspace.tsx` — local result-view state, progressive disclosure, detail open/close, and focus restoration.
- `frontend/src/features/workspace/AnalysisWorkspace.test.tsx` — view switching, single-fetch behavior, chord detail, focus restoration, and retained deletion/error coverage.
- `e2e/support.ts` — enter the structure-map view before selecting a timeline segment.
- `e2e/responsive.spec.ts` — verify desktop/tablet/mobile navigation placement and result-view disclosure.
- `DESIGN.md` — promote the approved palette and progressive-disclosure rules into the project design contract.

---

### Task 1: Lock the Morandi token contract

**Files:**
- Create: `frontend/src/styles/tokens.test.ts`
- Modify: `frontend/src/styles/tokens.css`
- Modify: `DESIGN.md`

**Interfaces:**
- Consumes: CSS custom properties imported by `frontend/src/styles/global.css`.
- Produces: stable semantic tokens `--bg`, `--surface`, `--surface-soft`, `--fg`, `--fg-2`, `--muted`, `--accent`, `--accent-strong`, `--accent-soft`, `--chord`, `--structure`, `--success`, `--warn`, `--danger`, `--border`, `--shadow-soft`, and `--safe-bottom`.

- [ ] **Step 1: Write the failing palette and contrast test**

Create `frontend/src/styles/tokens.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/styles/tokens.css', 'utf8')

function token(name: string): string {
  const value = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
  expect(value, `missing --${name}`).toBeDefined()
  return value as string
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5]
    .map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map((channel) =>
      channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4,
    )
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort(
    (left, right) => right - left,
  )
  return (values[0] + 0.05) / (values[1] + 0.05)
}

describe('Morandi design tokens', () => {
  it('uses the approved semantic palette', () => {
    expect(token('bg')).toBe('#f4f2ed')
    expect(token('surface')).toBe('#faf9f6')
    expect(token('fg')).toBe('#30332f')
    expect(token('accent')).toBe('#5d7162')
    expect(token('chord')).toBe('#8f6658')
    expect(token('structure')).toBe('#5c707c')
    expect(token('border')).toBe('#d9dcd5')
  })

  it.each([
    ['fg', 'bg'],
    ['fg-2', 'bg'],
    ['muted', 'bg'],
    ['accent', 'surface'],
    ['chord', 'surface'],
    ['structure', 'surface'],
    ['surface', 'accent'],
    ['surface', 'danger'],
  ])('keeps --%s readable on --%s', (foreground, background) => {
    expect(contrast(token(foreground), token(background))).toBeGreaterThanOrEqual(4.5)
  })
})
```

- [ ] **Step 2: Run the test and verify it fails against the warm editorial palette**

Run:

```powershell
npm --prefix frontend test -- src/styles/tokens.test.ts
```

Expected: FAIL because the current `--bg`, `--surface`, `--fg`, and `--accent` values do not match the approved palette and the new tokens are missing.

- [ ] **Step 3: Replace the root palette and add application tokens**

Update the color portion of `frontend/src/styles/tokens.css` to:

```css
:root {
  color-scheme: light;

  --bg: #f4f2ed;
  --surface: #faf9f6;
  --surface-soft: #eef0eb;
  --fg: #30332f;
  --fg-2: #59615b;
  --muted: #667068;
  --accent: #5d7162;
  --accent-strong: #495b4e;
  --accent-soft: #dfe6df;
  --chord: #8f6658;
  --structure: #5c707c;
  --success: #4f7558;
  --warn: #8f6658;
  --danger: #b33a3a;
  --border: #d9dcd5;
  --paper-rule: rgb(93 113 98 / 8%);
  --shadow-soft: 0 1rem 3rem rgb(48 51 47 / 8%);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
```

Keep the existing font, spacing, radius, transition, and breakpoint declarations. Change `--focus-ring` to `0 0 0 3px rgb(93 113 98 / 28%)`.

- [ ] **Step 4: Update the project design contract**

In `DESIGN.md`, change the design intent to “浅莫兰迪音乐工作室”，replace the color table with the values above, and add these exact rules under information architecture:

```markdown
- 未上传状态只展示上传核心流程，详细格式说明按需展开。
- 结果一级导航由“新的分析、歌曲概览、结构地图、深入分析”组成。
- 单个和弦或片段属于三级详情；关闭详情后恢复原选择和焦点。
```

- [ ] **Step 5: Run token and existing contrast tests**

Run:

```powershell
npm --prefix frontend test -- src/styles/tokens.test.ts src/pages/AnalysisPage.test.tsx
```

Expected: PASS, including all WCAG AA assertions.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/styles/tokens.css frontend/src/styles/tokens.test.ts DESIGN.md
git commit -m "style: establish Morandi design tokens"
```

---

### Task 2: Build the application header and compact lifecycle shell

**Files:**
- Create: `frontend/src/components/AppHeader.tsx`
- Create: `frontend/src/components/AppHeader.test.tsx`
- Modify: `frontend/src/pages/AnalysisPage.tsx`
- Modify: `frontend/src/pages/AnalysisPage.test.tsx`

**Interfaces:**
- Consumes: `Button` and the `analysisId` lifecycle already owned by `AnalysisPage`.
- Produces: `AppHeader({ analysisActive: boolean, onStartAnother: () => void })`.

- [ ] **Step 1: Write failing `AppHeader` tests**

Create `frontend/src/components/AppHeader.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppHeader } from './AppHeader'

describe('AppHeader', () => {
  it('shows a restrained brand header before an analysis starts', () => {
    render(<AppHeader analysisActive={false} onStartAnother={vi.fn()} />)

    expect(screen.getByText('MuseEcho')).toBeVisible()
    expect(screen.getByText('让音乐结构清晰可见')).toBeVisible()
    expect(screen.queryByRole('button', { name: '新的分析' })).not.toBeInTheDocument()
  })

  it('exposes the start-another action only in an active analysis', async () => {
    const user = userEvent.setup()
    const onStartAnother = vi.fn()
    render(<AppHeader analysisActive onStartAnother={onStartAnother} />)

    await user.click(screen.getByRole('button', { name: '新的分析' }))
    expect(onStartAnother).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run the header test and verify it fails**

Run:

```powershell
npm --prefix frontend test -- src/components/AppHeader.test.tsx
```

Expected: FAIL because `AppHeader.tsx` does not exist.

- [ ] **Step 3: Implement `AppHeader`**

Create `frontend/src/components/AppHeader.tsx`:

```tsx
import { Button } from './Button'

export interface AppHeaderProps {
  analysisActive: boolean
  onStartAnother: () => void
}

export function AppHeader({ analysisActive, onStartAnother }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <p className="brand">MuseEcho</p>
        <p className="app-header__tagline">让音乐结构清晰可见</p>
      </div>
      {analysisActive ? (
        <Button className="app-header__action" onClick={onStartAnother} variant="secondary">
          新的分析
        </Button>
      ) : (
        <p className="edition-mark">Evidence-led music analysis</p>
      )}
    </header>
  )
}
```

- [ ] **Step 4: Write the failing lifecycle hierarchy test**

Add to the `AnalysisPage` describe block:

```tsx
it('removes the landing hero and exposes a new-analysis action after activation', async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  window.history.replaceState(null, '', `/?analysis=${analysisId}`)

  render(
    <QueryClientProvider client={queryClient}>
      <AnalysisPage
        loadResult={vi.fn().mockResolvedValue(fixtureResult)}
        loadStatus={vi.fn().mockResolvedValue({
          analysis_id: analysisId,
          status: 'complete',
          stage: 'complete',
          progress: 1,
          error_code: null,
          expires_at: '2026-08-10T00:00:00+00:00',
          pipeline_version: 'museecho-analysis-v1',
          source_kind: 'real',
        })}
      />
    </QueryClientProvider>,
  )

  expect(await screen.findByRole('button', { name: '新的分析' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: '看见音乐的结构' })).not.toBeInTheDocument()
  window.history.replaceState(null, '', '/')
})
```

- [ ] **Step 5: Integrate the header and compact active state**

In `AnalysisPage.tsx`:

1. Import `AppHeader`.
2. Replace the existing `.masthead` element with:

```tsx
<AppHeader analysisActive={Boolean(analysisId)} onStartAnother={startAnother} />
```

3. Render `.workspace-intro` only when `analysisId` is null.
4. Remove the existing `分析其他音频` button below `AnalysisProgress`; the header action is now the single active-analysis entry point.
5. Keep the deleted state button `分析新的音频`, because it is the recovery action inside that status.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
npm --prefix frontend test -- src/components/AppHeader.test.tsx src/pages/AnalysisPage.test.tsx
```

Expected: PASS. The upload-to-status URL test and deletion test must remain green.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/components/AppHeader.tsx frontend/src/components/AppHeader.test.tsx frontend/src/pages/AnalysisPage.tsx frontend/src/pages/AnalysisPage.test.tsx
git commit -m "feat: add responsive analysis app header"
```

---

### Task 3: Make upload guidance progressively disclosed

**Files:**
- Modify: `frontend/src/features/upload/UploadForm.tsx`
- Modify: `frontend/src/features/upload/UploadForm.test.tsx`

**Interfaces:**
- Consumes: existing file validation and consent state.
- Produces: unchanged `UploadFormProps`, upload transport behavior, accepted suffixes, and consent contract; adds a native `details` disclosure named “查看支持格式与上传说明”.

- [ ] **Step 1: Write the failing disclosure test**

Add to `UploadForm.test.tsx`:

```tsx
it('keeps core limits visible and detailed format rules collapsed by default', async () => {
  const user = userEvent.setup()
  render(<UploadForm />)

  expect(screen.getByText(/最大 100 MB，最长 10 分钟/)).toBeVisible()
  const disclosure = screen.getByRole('group', { name: '查看支持格式与上传说明' })
  expect(disclosure).not.toHaveAttribute('open')
  expect(screen.getByText(/M4A 仅支持 AAC\/ALAC/)).not.toBeVisible()

  await user.click(screen.getByText('查看支持格式与上传说明', { selector: 'summary' }))
  expect(disclosure).toHaveAttribute('open')
  expect(screen.getByText(/M4A 仅支持 AAC\/ALAC/)).toBeVisible()
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
npm --prefix frontend test -- src/features/upload/UploadForm.test.tsx
```

Expected: FAIL because the current long guidance is always visible and no disclosure group exists.

- [ ] **Step 3: Split concise and detailed guidance**

Replace the current long `.field-help` paragraph with:

```tsx
<p className="field-help" id={helpId}>
  支持 WAV、MP3、FLAC、M4A、AAC、OGG 和 OPUS；最大 100 MB，最长 10 分钟。
</p>
<details
  aria-label="查看支持格式与上传说明"
  className="upload-guidance"
  name="upload-guidance"
>
  <summary>查看支持格式与上传说明</summary>
  <p>
    M4A 仅支持 AAC/ALAC，OGG 仅支持 Vorbis/Opus。浏览器文件名后缀或 MIME
    类型预检不能代替后端内容验证；不支持 DRM 或专有加密下载。
  </p>
</details>
```

Do not move, hide, pre-check, or weaken either consent checkbox.

- [ ] **Step 4: Run all upload tests**

Run:

```powershell
npm --prefix frontend test -- src/features/upload/UploadForm.test.tsx
```

Expected: PASS, including exact suffix, 100 MB boundary, true transport progress, ambiguous failure, and consent tests.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/features/upload/UploadForm.tsx frontend/src/features/upload/UploadForm.test.tsx
git commit -m "feat: simplify upload guidance"
```

---

### Task 4: Add typed result navigation

**Files:**
- Create: `frontend/src/features/workspace/WorkspaceNavigation.tsx`
- Create: `frontend/src/features/workspace/WorkspaceNavigation.test.tsx`

**Interfaces:**
- Produces: `export type WorkspaceView = 'overview' | 'map' | 'deep'`.
- Produces: `WorkspaceNavigation({ current, onChange })`, where `onChange(next: WorkspaceView): void`.
- Consumed by: `AnalysisWorkspace` in Task 6.

- [ ] **Step 1: Write the failing navigation test**

Create `frontend/src/features/workspace/WorkspaceNavigation.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceNavigation } from './WorkspaceNavigation'

describe('WorkspaceNavigation', () => {
  it('labels the three result views and marks the current view', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<WorkspaceNavigation current="overview" onChange={onChange} />)

    expect(screen.getByRole('navigation', { name: '分析功能' })).toBeVisible()
    expect(screen.getByRole('button', { name: /歌曲概览/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    expect(onChange).toHaveBeenCalledWith('map')
    await user.click(screen.getByRole('button', { name: /深入分析/ }))
    expect(onChange).toHaveBeenCalledWith('deep')
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
npm --prefix frontend test -- src/features/workspace/WorkspaceNavigation.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the typed navigation**

Create `WorkspaceNavigation.tsx`:

```tsx
export type WorkspaceView = 'overview' | 'map' | 'deep'

export interface WorkspaceNavigationProps {
  current: WorkspaceView
  onChange: (next: WorkspaceView) => void
}

const items: ReadonlyArray<{
  index: string
  label: string
  note: string
  view: WorkspaceView
}> = [
  { index: '01', label: '歌曲概览', note: '播放与关键事实', view: 'overview' },
  { index: '02', label: '结构地图', note: '时间轴与和弦', view: 'map' },
  { index: '03', label: '深入分析', note: '节奏、调性与动态', view: 'deep' },
]

export function WorkspaceNavigation({ current, onChange }: WorkspaceNavigationProps) {
  return (
    <nav aria-label="分析功能" className="workspace-nav">
      {items.map((item) => (
        <button
          aria-current={current === item.view ? 'page' : undefined}
          className="workspace-nav__item"
          key={item.view}
          onClick={() => onChange(item.view)}
          type="button"
        >
          <span className="workspace-nav__index" aria-hidden="true">{item.index}</span>
          <span>
            <strong>{item.label}</strong>
            <small>{item.note}</small>
          </span>
        </button>
      ))}
    </nav>
  )
}
```

- [ ] **Step 4: Run the navigation test**

Run:

```powershell
npm --prefix frontend test -- src/features/workspace/WorkspaceNavigation.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/features/workspace/WorkspaceNavigation.tsx frontend/src/features/workspace/WorkspaceNavigation.test.tsx
git commit -m "feat: add analysis workspace navigation"
```

---

### Task 5: Add an honest deep-analysis hub

**Files:**
- Create: `frontend/src/features/workspace/AnalysisFeatureHub.tsx`
- Create: `frontend/src/features/workspace/AnalysisFeatureHub.test.tsx`

**Interfaces:**
- Consumes: `AnalysisResult` and the existing `confidenceLevel` helper.
- Produces: `AnalysisFeatureHub({ result, onOpenMap })`, where `onOpenMap(): void`.
- Does not request data or infer mood, genre, instruments, or unsupported musical claims.

- [ ] **Step 1: Write failing feature-hub tests**

Create `AnalysisFeatureHub.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { AnalysisFeatureHub } from './AnalysisFeatureHub'

describe('AnalysisFeatureHub', () => {
  it('summarizes only persisted rhythm, tonality, chord, and energy facts', async () => {
    const user = userEvent.setup()
    const onOpenMap = vi.fn()
    render(<AnalysisFeatureHub onOpenMap={onOpenMap} result={fixtureResult} />)

    expect(screen.getByRole('heading', { name: '深入分析' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '节奏' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '调性' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '和弦线索' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '动态强弱' })).toBeVisible()
    expect(screen.queryByText(/情绪|氛围|乐器/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '在结构地图中查看' }))
    expect(onOpenMap).toHaveBeenCalledTimes(1)
  })

  it('uses an explicit unknown label when confidence is unusable', () => {
    render(
      <AnalysisFeatureHub
        onOpenMap={vi.fn()}
        result={{
          ...fixtureResult,
          track: {
            ...fixtureResult.track,
            bpm: null,
            bpm_confidence: 0,
            key_tonic: null,
            key_confidence: 0,
            mode: null,
          },
        }}
      />,
    )

    expect(screen.getAllByText('暂未判定')).toHaveLength(2)
  })
})
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/features/workspace/AnalysisFeatureHub.test.tsx
```

Expected: FAIL because `AnalysisFeatureHub` does not exist.

- [ ] **Step 3: Implement the feature hub from persisted fields**

Create `AnalysisFeatureHub.tsx` with this component contract and derivation:

```tsx
import type { AnalysisResult } from '../../api/types'
import { Button } from '../../components/Button'
import { confidenceLevel } from '../confidence'

export interface AnalysisFeatureHubProps {
  onOpenMap: () => void
  result: AnalysisResult
}

export function AnalysisFeatureHub({ onOpenMap, result }: AnalysisFeatureHubProps) {
  const { track } = result
  const bpm =
    confidenceLevel(track.bpm_confidence) === 'unknown' || track.bpm === null
      ? '暂未判定'
      : `${Math.round(track.bpm)} BPM`
  const tonality =
    confidenceLevel(track.key_confidence) === 'unknown' ||
    !track.key_tonic ||
    !track.mode
      ? '暂未判定'
      : `${track.key_tonic} ${track.mode === 'major' ? '大调' : '小调'}`
  const chordCount = result.chords.filter((chord) => chord.symbol !== 'unknown').length
  const energyPoints =
    result.time_series.find((series) => series.kind === 'energy')?.points.length ?? 0

  return (
    <section aria-labelledby="feature-hub-title" className="feature-hub">
      <header className="feature-hub__header">
        <p className="eyebrow">按需展开真实证据</p>
        <h2 id="feature-hub-title">深入分析</h2>
      </header>
      <div className="feature-hub__grid">
        <FeatureFact label="节奏" value={bpm} />
        <FeatureFact label="调性" value={tonality} />
        <FeatureFact label="和弦线索" value={`${chordCount} 个可见候选`} />
        <FeatureFact label="动态强弱" value={`${energyPoints} 个采样点`} />
      </div>
      <Button onClick={onOpenMap} variant="secondary">在结构地图中查看</Button>
    </section>
  )
}

function FeatureFact({ label, value }: { label: string; value: string }) {
  return (
    <article className="feature-fact">
      <h3>{label}</h3>
      <p>{value}</p>
    </article>
  )
}
```

- [ ] **Step 4: Run the feature-hub tests**

Run:

```powershell
npm --prefix frontend test -- src/features/workspace/AnalysisFeatureHub.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/features/workspace/AnalysisFeatureHub.tsx frontend/src/features/workspace/AnalysisFeatureHub.test.tsx
git commit -m "feat: add honest deep analysis hub"
```

---

### Task 6: Integrate progressive result views and chord detail return

**Files:**
- Modify: `frontend/src/features/timeline/Timeline.tsx`
- Modify: `frontend/src/features/timeline/Timeline.test.tsx`
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.tsx`
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`

**Interfaces:**
- Extends: `TimelineProps.onChordSelect?: (chord: ChordResult, trigger: HTMLButtonElement) => void`.
- Adds: `TimelineProps.selectedChord?: ChordResult | null`.
- Consumes: `WorkspaceView`, `WorkspaceNavigation`, `AnalysisFeatureHub`, existing `TimelineController`, `AudioPlayer`, `MusicDNA`, `ChordDetails`, and `RetentionPanel`.
- Preserves: one result query, one timeline controller, one audio element, and the existing deletion cache cleanup.

- [ ] **Step 1: Write failing timeline selection-state coverage**

In `Timeline.test.tsx`, add a wrapper test that renders `Timeline` with `selectedChord={richResult.chords[0]}`, clicks the corresponding chord button, and asserts:

```tsx
expect(screen.getByRole('button', { name: /和弦 C/ })).toHaveAttribute(
  'aria-pressed',
  'true',
)
expect(onChordSelect).toHaveBeenCalledWith(
  richResult.chords[0],
  expect.any(HTMLButtonElement),
)
```

- [ ] **Step 2: Update workspace tests for progressive disclosure**

Replace the first three happy-path tests in `AnalysisWorkspace.test.tsx` with:

```tsx
it('loads one result and initially exposes only the overview', async () => {
  const { loadResult } = renderWorkspace()

  expect(await screen.findByRole('heading', { name: 'Music DNA' })).toBeVisible()
  expect(screen.getByRole('heading', { name: '播放器' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: '结构地图' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '深入分析' })).not.toBeInTheDocument()
  expect(loadResult).toHaveBeenCalledTimes(1)
})

it('switches views without refetching and opens chord theory as a returnable detail', async () => {
  const user = userEvent.setup()
  const { container, loadResult } = renderWorkspace()
  await screen.findByRole('heading', { name: 'Music DNA' })

  await user.click(screen.getByRole('button', { name: /结构地图/ }))
  const chord = screen.getByRole('button', { name: /和弦 G/ })
  await user.click(chord)

  expect(container.querySelector('audio')?.currentTime).toBe(8)
  expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
  expect(screen.getByRole('button', { name: '返回结构地图' })).toBeVisible()

  await user.click(screen.getByRole('button', { name: '返回结构地图' }))
  expect(screen.queryByRole('heading', { name: 'G 和弦' })).not.toBeInTheDocument()
  expect(chord).toHaveFocus()
  expect(loadResult).toHaveBeenCalledTimes(1)
})

it('keeps secondary data management outside the primary result views', async () => {
  const user = userEvent.setup()
  renderWorkspace()
  await screen.findByRole('heading', { name: 'Music DNA' })

  await user.click(screen.getByRole('button', { name: /结构地图/ }))
  expect(screen.getByRole('group', { name: '片段选择轨道' })).toBeVisible()
  expect(screen.getByRole('group', { name: '片段选择' })).toBeVisible()
  expect(screen.getByRole('group', { name: '管理分析数据' })).not.toHaveAttribute('open')
})
```

Keep the existing result failure/retry test unchanged.

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/features/timeline/Timeline.test.tsx src/features/workspace/AnalysisWorkspace.test.tsx
```

Expected: FAIL because the selected state, result navigation, and returnable detail are not implemented.

- [ ] **Step 4: Extend the timeline chord callback**

In `Timeline.tsx`:

1. Add `selectedChord?: ChordResult | null` to `TimelineProps`.
2. Change the callback type to `(chord: ChordResult, trigger: HTMLButtonElement) => void`.
3. On each chord button set:

```tsx
aria-pressed={selectedChord === chord}
onClick={(event) => {
  timeline.seek(chord.start_seconds)
  onChordSelect?.(chord, event.currentTarget)
}}
```

- [ ] **Step 5: Refactor `LoadedWorkspace` into view panels**

In `AnalysisWorkspace.tsx`, add imports for `useRef`, `AnalysisFeatureHub`, `WorkspaceNavigation`, and `WorkspaceView`. Add this state inside `LoadedWorkspace`:

```tsx
const [currentView, setCurrentView] = useState<WorkspaceView>('overview')
const [selectedChord, setSelectedChord] = useState<ChordResult | null>(null)
const lastChordTrigger = useRef<HTMLButtonElement | null>(null)

const openChord = (chord: ChordResult, trigger: HTMLButtonElement) => {
  lastChordTrigger.current = trigger
  setSelectedChord(chord)
}

const closeChord = () => {
  setSelectedChord(null)
  lastChordTrigger.current?.focus()
}
```

Replace the current `music-workspace` return body with this semantic structure:

```tsx
<div className="music-workspace">
  <WorkspaceNavigation current={currentView} onChange={setCurrentView} />
  <div className="music-workspace__stage">
    {currentView === 'overview' ? (
      <section aria-label="歌曲概览" className="workspace-view workspace-view--overview">
        <AudioPlayer analysisId={result.analysis_id} timeline={timeline} />
        <MusicDNA result={result} />
      </section>
    ) : null}

    {currentView === 'map' ? (
      <section aria-label="结构地图工作区" className="workspace-view workspace-view--map">
        <div className={`workspace-map-layout${selectedChord ? ' workspace-map-layout--detail' : ''}`}>
          <Timeline
            onChordSelect={openChord}
            result={result}
            selectedChord={selectedChord}
            timeline={timeline}
          />
          {selectedChord ? (
            <aside aria-label="当前和弦详情" className="workspace-detail">
              <Button onClick={closeChord} variant="secondary">返回结构地图</Button>
              <ChordDetails chord={selectedChord} />
            </aside>
          ) : null}
        </div>
      </section>
    ) : null}

    {currentView === 'deep' ? (
      <div className="workspace-view workspace-view--deep">
        <AnalysisFeatureHub onOpenMap={() => setCurrentView('map')} result={result} />
      </div>
    ) : null}

    <div className="analysis-support">
      <RetentionPanel
        analysisId={result.analysis_id}
        expiresAt={expiresAt}
        onDeleted={finishDeletion}
        remove={removeAnalysis}
      />
    </div>
  </div>
</div>
```

- [ ] **Step 6: Run workspace and timeline tests**

Run:

```powershell
npm --prefix frontend test -- src/features/timeline/Timeline.test.tsx src/features/workspace/AnalysisWorkspace.test.tsx
```

Expected: PASS. Confirm `loadResult` is called once during all presentation-only view changes.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/features/timeline/Timeline.tsx frontend/src/features/timeline/Timeline.test.tsx frontend/src/features/workspace/AnalysisWorkspace.tsx frontend/src/features/workspace/AnalysisWorkspace.test.tsx
git commit -m "feat: progressively disclose analysis results"
```

---

### Task 7: Implement responsive application layouts and transitions

**Files:**
- Modify: `frontend/src/styles/global.css`
- Modify: `e2e/support.ts`
- Modify: `e2e/responsive.spec.ts`

**Interfaces:**
- Consumes: `.app-header`, `.workspace-nav`, `.music-workspace__stage`, `.workspace-view`, `.workspace-map-layout`, `.workspace-detail`, `.feature-hub`, and `.upload-guidance` classes created earlier.
- Produces: desktop side navigation, tablet top navigation, mobile bottom navigation, safe-area padding, and reduced-motion-safe view transitions.

- [ ] **Step 1: Update E2E helpers and write failing responsive assertions**

At the start of `selectTimelineSegment` in `e2e/support.ts`, add:

```ts
const mapButton = page.getByRole('button', { name: /结构地图/ })
if (await mapButton.isVisible()) await mapButton.click()
```

In `e2e/responsive.spec.ts`, keep the existing overflow loop and replace the always-visible overview/map assumptions with:

```ts
const navigation = page.getByRole('navigation', { name: '分析功能' })
const navBox = await navigation.boundingBox()
expect(navBox).not.toBeNull()
if (!navBox) continue

if (viewport.width <= 599) {
  expect(navBox.y + navBox.height).toBeGreaterThanOrEqual(viewport.height - 4)
} else {
  expect(navBox.y).toBeGreaterThanOrEqual(0)
}

await page.getByRole('button', { name: /结构地图/ }).click()
await expect(page.getByRole('heading', { name: '结构地图' })).toBeVisible()
await expect(page.getByRole('heading', { name: '播放器' })).not.toBeVisible()
await page.getByRole('button', { name: /歌曲概览/ }).click()
await expect(page.getByRole('heading', { name: '播放器' })).toBeVisible()
```

After the loop, click the structure-map navigation before the existing keyboard selection assertions.

- [ ] **Step 2: Run the responsive E2E test and verify it fails**

Run:

```powershell
npm run e2e -- --grep "desktop, tablet, and mobile layouts"
```

Expected: FAIL because the new navigation layout and progressive view visibility are not yet styled and integrated end-to-end.

- [ ] **Step 3: Replace shell styles and add component styles**

Update `global.css` with these exact layout rules, merging them with existing component-specific styles rather than duplicating selectors:

```css
body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background:
    linear-gradient(90deg, transparent 0 49.8%, var(--paper-rule) 50%, transparent 50.2%) 0 0 / 5rem 100%,
    var(--bg);
}

.app-shell {
  width: min(100% - 3rem, 1280px);
  margin-inline: auto;
  padding: max(var(--space-5), env(safe-area-inset-top, 0px)) 0
    calc(var(--space-section) + var(--safe-bottom));
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  min-height: 4.25rem;
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border);
}

.app-header__brand {
  display: flex;
  align-items: baseline;
  gap: var(--space-4);
}

.app-header__tagline {
  margin: 0;
  color: var(--muted);
  font-size: 0.82rem;
}

.analysis-workspace {
  padding-top: clamp(2.75rem, 7vw, 5.5rem);
}

.analysis-workspace--active {
  padding-top: var(--space-5);
}

.music-workspace {
  display: grid;
  grid-template-columns: minmax(10.5rem, 2fr) minmax(0, 10fr);
  gap: var(--space-6);
  padding-top: var(--space-5);
  border-top: 1px solid var(--border);
}

.workspace-nav {
  position: sticky;
  top: var(--space-4);
  display: grid;
  gap: var(--space-2);
  align-self: start;
}

.workspace-nav__item {
  display: grid;
  grid-template-columns: 2rem 1fr;
  gap: var(--space-2);
  align-items: start;
  min-height: 3.5rem;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  padding: var(--space-3);
  color: var(--fg-2);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    transform var(--transition-fast);
}

.workspace-nav__item:hover {
  background: var(--surface-soft);
}

.workspace-nav__item[aria-current='page'] {
  border-color: var(--border);
  color: var(--fg);
  background: var(--surface);
}

.workspace-nav__item:active {
  transform: scale(0.985);
}

.workspace-nav__index {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 0.72rem;
}

.workspace-nav__item strong,
.workspace-nav__item small {
  display: block;
}

.workspace-nav__item small {
  margin-top: var(--space-1);
  color: var(--muted);
  font-size: 0.72rem;
}

.music-workspace__stage,
.workspace-view {
  min-width: 0;
}

.music-workspace__stage {
  display: grid;
  gap: var(--space-6);
}

.workspace-view {
  animation: workspace-view-in var(--transition-standard) both;
}

.workspace-view--overview {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--space-6);
  align-items: start;
}

.workspace-map-layout {
  display: grid;
  gap: var(--space-5);
}

.workspace-map-layout--detail {
  grid-template-columns: minmax(0, 2fr) minmax(18rem, 1fr);
}

.workspace-detail {
  align-self: start;
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-soft);
}

.workspace-detail .chord-details {
  margin-top: var(--space-4);
  padding-inline: 0;
  border-bottom: 0;
}

.feature-hub {
  display: grid;
  gap: var(--space-5);
}

.feature-hub h2,
.feature-fact h3 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 400;
}

.feature-hub__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.feature-fact {
  min-width: 0;
  padding: var(--space-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.feature-fact p {
  margin: var(--space-3) 0 0;
  color: var(--fg-2);
}

.upload-guidance {
  color: var(--fg-2);
  font-size: 0.86rem;
}

.upload-guidance summary {
  color: var(--accent-strong);
  font-weight: 700;
  cursor: pointer;
}

@keyframes workspace-view-in {
  from {
    opacity: 0;
    transform: translateY(0.4rem);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

- [ ] **Step 4: Add tablet and mobile transformations**

Merge these rules into the existing media queries:

```css
@media (max-width: 899px) {
  .app-shell {
    width: min(100% - 2rem, 48rem);
  }

  .music-workspace {
    display: block;
  }

  .workspace-nav {
    position: sticky;
    z-index: 8;
    top: 0;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    margin-bottom: var(--space-5);
    padding-block: var(--space-2);
    background: color-mix(in srgb, var(--bg) 94%, transparent);
    backdrop-filter: blur(0.75rem);
  }

  .workspace-nav__item {
    grid-template-columns: 1fr;
  }

  .workspace-nav__index,
  .workspace-nav__item small {
    display: none;
  }

  .workspace-map-layout--detail {
    grid-template-columns: minmax(0, 3fr) minmax(15rem, 2fr);
  }
}

@media (max-width: 599px) {
  .app-shell {
    width: min(100% - 2rem, 34rem);
    padding-bottom: calc(7rem + var(--safe-bottom));
  }

  .app-header__tagline,
  .app-header .edition-mark {
    display: none;
  }

  .workspace-intro {
    display: block;
  }

  .display-title {
    font-size: clamp(2.75rem, 14vw, 4.25rem);
  }

  .empty-workflow,
  .workspace-view--overview,
  .feature-hub__grid {
    grid-template-columns: 1fr;
  }

  .workspace-nav {
    position: fixed;
    z-index: 20;
    right: 0;
    bottom: 0;
    left: 0;
    top: auto;
    gap: 0;
    margin: 0;
    padding: var(--space-2) max(var(--space-3), env(safe-area-inset-right, 0px))
      calc(var(--space-2) + var(--safe-bottom))
      max(var(--space-3), env(safe-area-inset-left, 0px));
    border-top: 1px solid var(--border);
    background: color-mix(in srgb, var(--surface) 96%, transparent);
    box-shadow: 0 -0.75rem 2rem rgb(48 51 47 / 8%);
  }

  .workspace-nav__item {
    min-height: 3rem;
    place-items: center;
    border-radius: var(--radius-sm);
    padding: var(--space-2);
    text-align: center;
  }

  .workspace-map-layout--detail {
    display: block;
  }

  .workspace-detail {
    position: fixed;
    z-index: 30;
    inset: 0;
    overflow-y: auto;
    padding: max(var(--space-5), env(safe-area-inset-top, 0px)) var(--space-4)
      calc(var(--space-6) + var(--safe-bottom));
    border: 0;
    border-radius: 0;
  }
}
```

Keep the existing global `prefers-reduced-motion` block. Its universal animation-duration override must continue to neutralize `workspace-view-in`.

- [ ] **Step 5: Run component, responsive, and primary journey tests**

Run:

```powershell
npm --prefix frontend test
npm run e2e -- --grep "desktop, tablet, and mobile layouts|upload to delete"
```

Expected: PASS. No viewport may have horizontal overflow, and the upload-to-delete flow must emit no runtime or network errors.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/styles/global.css e2e/support.ts e2e/responsive.spec.ts
git commit -m "style: add adaptive music workspace layouts"
```

---

### Task 8: Run the complete frontend quality gate

**Files:**
- Verify only; modify the files from Tasks 1–7 only if a failing check exposes a regression within this slice.

**Interfaces:**
- Verifies the complete first-slice deliverable against the approved spec and repository toolchain.
- Produces no backend or ML changes.

- [ ] **Step 1: Confirm the diff stays inside the authorized boundary**

Run:

```powershell
git status --short
git diff --name-only HEAD~7..HEAD
```

Expected: only `frontend/`, `e2e/`, and `DESIGN.md` paths listed in this plan. There must be no files under `src/museecho/`, `ml/`, `models/`, `migrations/`, or `deploy/`.

- [ ] **Step 2: Run frontend type checking and unit tests**

Run:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend test
```

Expected: both commands exit 0 with all frontend tests passing.

- [ ] **Step 3: Run frontend production build and E2E type checking**

Run:

```powershell
npm --prefix frontend run build
npm run typecheck
```

Expected: both commands exit 0 with no TypeScript errors.

- [ ] **Step 4: Run the complete E2E suite**

Run:

```powershell
npm run e2e
```

Expected: all Playwright tests pass, including security, responsive, upload-to-delete, audio range, keyboard selection, and refresh restoration coverage.

- [ ] **Step 5: Review the production UI at the three canonical viewports**

Use the built E2E app and inspect 390×844, 768×1024, and 1440×900. Confirm:

- the empty state has one dominant upload action and collapsed detailed guidance;
- the active state has no large landing hero;
- desktop uses side navigation, tablet uses top navigation, and mobile uses bottom navigation;
- selecting a chord opens a readable detail and “返回结构地图” restores focus;
- no text overlaps, no control is clipped, and no page-level horizontal overflow appears;
- reduced-motion mode leaves every state change understandable.

- [ ] **Step 6: Record final evidence**

Run:

```powershell
git status --short
git log -8 --oneline
```

Expected: clean working tree and one reviewable commit per implementation task. If verification required a fix, add only the affected planned files and commit with `fix: close frontend foundation verification gap` before repeating the failed gate.
