# MuseEcho 和弦实验室与可缩放结构地图实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改后端模型、API、上传或音频解码逻辑的前提下，把结构地图升级为五轨统一缩放的时间画布，并把和弦详情升级为桌面下方大面板、手机和平板全屏的可交互和弦实验室。

**Architecture:** `useTimeline` 继续独占歌曲播放时间、seek、选区和唯一 `<audio>`；新增 `useTimelineViewport` 只管理缩放、画布宽度和播放头锚定。`Timeline` 使用一个固定标签列加一个横向滚动的统一内容画布；`ChordDetails` 组合 `ChordOrbit`、`ChordPiano` 与 `useToneAudition`，其会话状态随详情卸载而清空；`AnalysisWorkspace` 只负责详情打开、响应式 portal、焦点和结果所有权。

**Tech Stack:** React 19、TypeScript、CSS custom properties、Web Audio API、Vitest、Testing Library、Playwright、现有 PWA/Vite 构建与独立 Docker E2E。

**Spec:** `docs/superpowers/specs/2026-08-24-chord-lab-timeline-interactions-design.md`

## Global Constraints

- 不修改分析 API、模型、任务编排、上传或音频解码逻辑。
- 不新增 URL 参数，不重新请求分析结果，不改变 `analysisId`。
- 页面始终只保留一个歌曲 `<audio>`；试听使用 Web Audio，不新增网络音频资源。
- 缩放范围固定为 `1–4`，步长固定为 `0.25`；缩放只改变显示宽度，不重采样真实数组。
- 波形、段落、和弦、动态强弱、事件、选区和播放头必须共用同一内容宽度与时间坐标。
- `MOBILE_WORKSPACE_QUERY` 仍为最大 599px，只控制手机和弦列表；新增最大 1023px 的详情断点控制手机和平板全屏详情。
- `A/B/C` 只能显示为“段落 A/B/C”；只有 `intro/verse/pre_chorus/chorus/bridge/outro` 可固定映射为中文语义。
- 事件文案只能来自 `energy_changes` 的方向、时间、强度与置信度，不出现乐器或演唱语义。
- unknown、低置信度或缺失 theory 时不展示轨道、情绪或情境推断。
- 视觉遵守 `DESIGN.md` 的 Warm Editorial、浅莫兰迪语义令牌、150/240ms 克制反馈和真实性要求。
- `prefers-reduced-motion` 下轨道静止；键盘、解释、选择和试听能力仍可用。
- 每项行为修改严格执行 RED → GREEN → 回归测试 → 独立提交。
- Docker E2E 使用本任务独立的 compose project/container 名称，禁止复用或停止其他并行任务的容器。

---

## File map

- `frontend/src/features/timeline/useTimelineViewport.ts`：缩放常量、纯几何函数、画布测量、播放头锚定和滚动视窗 ref。
- `frontend/src/features/timeline/useTimelineViewport.test.tsx`：倍率、坐标、锚定、零时长和 ResizeObserver 行为。
- `frontend/src/features/timeline/Timeline.tsx`：统一时间画布、真实五轨、空状态、段落/事件文案和播放头邻近聚焦。
- `frontend/src/features/timeline/Timeline.test.tsx`：统一宽度、缩放、真实性映射、焦点提示、移动端替代路径和原有 seek/选区回归。
- `frontend/src/features/chords/useToneAudition.ts`：音名解析、频率换算、一次性钢琴式衰减单音、停止与释放。
- `frontend/src/features/chords/useToneAudition.test.tsx`：升降音映射、用户手势试听、失败降级和 unmount 清理。
- `frontend/src/features/chords/ChordOrbit.tsx`：三轨错相旋转、悬停/焦点暂停、浮层、连续组成音选择。
- `frontend/src/features/chords/ChordPiano.tsx`：组成音对应键位和短暂按键反馈，不持有音频资源。
- `frontend/src/features/chords/ChordOrbit.test.tsx`：C → E → G 连续激活、命中层、暂停恢复、浮层和钢琴反馈。
- `frontend/src/features/chords/ChordDetails.tsx`：详情会话、真实性分支和“构成 / 听感 / 情境”通用乐理。
- `frontend/src/features/chords/ChordDetails.test.tsx`：文案边界、状态清空、无可靠 theory 降级与试听失败提示。
- `frontend/src/hooks/useMediaQuery.ts`：新增 `FULLSCREEN_CHORD_DETAIL_QUERY = '(max-width: 1023px)'`。
- `frontend/src/features/workspace/AnalysisWorkspace.tsx`：桌面下方面板、手机/平板 portal、inert、焦点陷阱与返回焦点。
- `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`：599/600/1023/1024 边界、单 audio、单次加载和详情会话重置。
- `frontend/src/styles/global.css`：统一画布、缩放工具栏、轨道聚焦、和弦轨道/钢琴、详情布局、断点和 reduced motion。
- `e2e/responsive.spec.ts`：桌面/平板/手机布局、统一缩放、全屏边界、无页面横向溢出和状态重置。

---

### Task 1: 独立的时间轴视图几何与播放头锚定

**Files:**
- Create: `frontend/src/features/timeline/useTimelineViewport.ts`
- Create: `frontend/src/features/timeline/useTimelineViewport.test.tsx`

**Interfaces:**
- Consumes: `duration: number`、`currentTime: number` 和内容视窗 `HTMLDivElement.clientWidth`。
- Produces: `TIMELINE_MIN_ZOOM = 1`、`TIMELINE_MAX_ZOOM = 4`、`TIMELINE_ZOOM_STEP = 0.25`。
- Produces: `clampTimelineZoom(value: number): number`、`timelineCanvasWidth(viewportWidth: number, zoom: number): number`、`secondsToCanvasX(seconds: number, duration: number, contentWidth: number): number`、`anchoredScrollLeft(currentTime: number, duration: number, contentWidth: number, viewportWidth: number): number`。
- Produces: `useTimelineViewport({ duration, currentTime }): TimelineViewportController`，其中 controller 精确包含 `zoom`、`setZoom`、`viewportRef`、`contentWidth` 和 `disabled`。

- [ ] **Step 1: 写入失败的几何和 hook 测试**

```tsx
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  anchoredScrollLeft,
  clampTimelineZoom,
  secondsToCanvasX,
  timelineCanvasWidth,
  useTimelineViewport,
} from './useTimelineViewport'

describe('useTimelineViewport', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('clamps zoom and uses one finite canvas coordinate', () => {
    expect(clampTimelineZoom(0.5)).toBe(1)
    expect(clampTimelineZoom(2.13)).toBe(2.25)
    expect(clampTimelineZoom(9)).toBe(4)
    expect(timelineCanvasWidth(800, 2.25)).toBe(1800)
    expect(secondsToCanvasX(30, 120, 1800)).toBe(450)
    expect(secondsToCanvasX(30, 0, 1800)).toBe(0)
  })

  it('centres the playhead while clamping naturally at both ends', () => {
    expect(anchoredScrollLeft(0, 120, 2400, 800)).toBe(0)
    expect(anchoredScrollLeft(60, 120, 2400, 800)).toBe(800)
    expect(anchoredScrollLeft(120, 120, 2400, 800)).toBe(1600)
    expect(anchoredScrollLeft(60, 0, 2400, 800)).toBe(0)
  })

  it('updates width and anchored scroll only inside its own viewport', () => {
    let resize: ResizeObserverCallback = () => undefined
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback }
      observe() {}
      disconnect() {}
    })
    const { result } = renderHook(() =>
      useTimelineViewport({ duration: 120, currentTime: 60 }),
    )
    const viewport = document.createElement('div')
    Object.defineProperty(viewport, 'clientWidth', { value: 800 })
    act(() => {
      result.current.viewportRef.current = viewport
      resize([{ contentRect: { width: 800 } } as ResizeObserverEntry], {} as ResizeObserver)
    })
    act(() => result.current.setZoom(2))
    expect(result.current.contentWidth).toBe(1600)
    expect(viewport.scrollLeft).toBe(400)
  })
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/useTimelineViewport.test.tsx`

Expected: FAIL，提示无法解析 `./useTimelineViewport`。

- [ ] **Step 3: 实现纯几何函数和视图 hook**

```ts
import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { finiteClamp } from './useTimeline'

export const TIMELINE_MIN_ZOOM = 1
export const TIMELINE_MAX_ZOOM = 4
export const TIMELINE_ZOOM_STEP = 0.25

export interface TimelineViewportController {
  zoom: number
  setZoom: (zoom: number) => void
  viewportRef: RefObject<HTMLDivElement | null>
  contentWidth: number
  disabled: boolean
}

export function clampTimelineZoom(value: number): number {
  const stepped = Math.round(value / TIMELINE_ZOOM_STEP) * TIMELINE_ZOOM_STEP
  return finiteClamp(stepped, TIMELINE_MIN_ZOOM, TIMELINE_MAX_ZOOM)
}

export function timelineCanvasWidth(viewportWidth: number, zoom: number): number {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return 0
  return viewportWidth * clampTimelineZoom(zoom)
}

export function secondsToCanvasX(
  seconds: number,
  duration: number,
  contentWidth: number,
): number {
  if (!Number.isFinite(duration) || duration <= 0 || contentWidth <= 0) return 0
  return finiteClamp(seconds / duration, 0, 1) * contentWidth
}

export function anchoredScrollLeft(
  currentTime: number,
  duration: number,
  contentWidth: number,
  viewportWidth: number,
): number {
  if (duration <= 0 || viewportWidth <= 0 || contentWidth <= viewportWidth) return 0
  return finiteClamp(
    secondsToCanvasX(currentTime, duration, contentWidth) - viewportWidth / 2,
    0,
    contentWidth - viewportWidth,
  )
}

export function useTimelineViewport({
  duration,
  currentTime,
}: {
  duration: number
  currentTime: number
}): TimelineViewportController {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [viewportWidth, setViewportWidth] = useState(0)
  const [zoom, setZoomState] = useState(TIMELINE_MIN_ZOOM)
  const pendingAnchor = useRef(false)
  const contentWidth = timelineCanvasWidth(viewportWidth, zoom)
  const disabled = !Number.isFinite(duration) || duration <= 0 || viewportWidth <= 0

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const measure = () => setViewportWidth(viewport.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (!pendingAnchor.current || !viewportRef.current) return
    pendingAnchor.current = false
    viewportRef.current.scrollLeft = anchoredScrollLeft(
      currentTime,
      duration,
      contentWidth,
      viewportWidth,
    )
  }, [contentWidth, currentTime, duration, viewportWidth])

  const setZoom = useCallback((next: number) => {
    pendingAnchor.current = true
    setZoomState(clampTimelineZoom(next))
  }, [])

  return { zoom, setZoom, viewportRef, contentWidth, disabled }
}
```

- [ ] **Step 4: 运行定向测试并确认 GREEN**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/useTimelineViewport.test.tsx`

Expected: PASS，3 tests passed。

- [ ] **Step 5: 提交几何层**

```bash
git add frontend/src/features/timeline/useTimelineViewport.ts frontend/src/features/timeline/useTimelineViewport.test.tsx
git commit -m "feat: add anchored timeline viewport"
```

---

### Task 2: 将真实五轨重构为同一可缩放画布

**Files:**
- Modify: `frontend/src/features/timeline/Timeline.tsx:21-352`
- Modify: `frontend/src/features/timeline/Timeline.test.tsx:130-325`
- Modify: `frontend/src/styles/global.css:704-889`

**Interfaces:**
- Consumes: Task 1 的 `useTimelineViewport` controller。
- Produces: `sectionDisplayLabel(label: string): string` 和 `energyEventLabel(event: EnergyChangeSummary): string`。
- Produces: DOM 契约 `.timeline__viewport > .timeline__content`；所有轨道内容、选区和播放头必须位于唯一 `.timeline__content` 下。

- [ ] **Step 1: 添加失败测试，锁定统一宽度、真实空状态与语义文案**

```tsx
it('keeps waveform, sections, chords, energy, events, selection and playhead in one canvas', () => {
  const { container } = render(<RichHarness />)
  const content = container.querySelector('.timeline__content')
  expect(content).toBeVisible()
  expect(content?.querySelectorAll('[data-timeline-layer]')).toHaveLength(7)
  expect(container.querySelectorAll('.timeline__content')).toHaveLength(1)
  expect(screen.getByText('段落 A')).toBeVisible()
  expect(screen.getByText('段落 B')).toBeVisible()
  expect(screen.queryByText('主歌')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '动态上升 0:06，强度 40%' })).toBeVisible()
})

it('uses fixed translations only for explicit semantic section labels', () => {
  expect(sectionDisplayLabel('verse')).toBe('主歌')
  expect(sectionDisplayLabel('CHORUS')).toBe('副歌')
  expect(sectionDisplayLabel('A')).toBe('段落 A')
  expect(sectionDisplayLabel('')).toBe('未命名段落')
})

it('shows independent truthful empty states without demonstration data', () => {
  const emptyResult = {
    ...richResult,
    sections: [],
    time_series: [],
    track: { ...richResult.track, summary: null },
  }
  function EmptyHarness() {
    const timeline = useTimeline(emptyResult.track.duration_seconds)
    return <Timeline result={emptyResult} timeline={timeline} />
  }
  render(<EmptyHarness />)
  expect(screen.getByText('暂无波形摘要')).toBeVisible()
  expect(screen.getByText('暂无段落信息')).toBeVisible()
  expect(screen.getByText('暂无动态曲线')).toBeVisible()
  expect(screen.getByText('暂无事件')).toBeVisible()
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/Timeline.test.tsx`

Expected: FAIL，缺少 `.timeline__content`、段落文字和独立空状态。

- [ ] **Step 3: 在 `Timeline` 接入 viewport controller 和缩放工具栏**

```tsx
const viewport = useTimelineViewport({
  duration: timeline.duration,
  currentTime: timeline.currentTime,
})

<div className="timeline__heading">
  <div>
    <p className="eyebrow">共享时间坐标</p>
    <h2 id="timeline-title">结构地图</h2>
  </div>
  <output aria-label="当前时间">{formatTime(timeline.currentTime)}</output>
</div>
<label className="timeline__zoom">
  <span>时间轴缩放</span>
  <input
    aria-label="时间轴缩放"
    disabled={viewport.disabled}
    max={TIMELINE_MAX_ZOOM}
    min={TIMELINE_MIN_ZOOM}
    onChange={(event) => viewport.setZoom(event.currentTarget.valueAsNumber)}
    step={TIMELINE_ZOOM_STEP}
    type="range"
    value={viewport.zoom}
  />
  <output>{viewport.zoom.toFixed(2)}×</output>
</label>
```

- [ ] **Step 4: 用固定标签列和唯一滚动画布替换原 `.timeline__canvas`**

```tsx
<div className="timeline__frame">
  <div aria-hidden="true" className="timeline__labels">
    {['选区', '波形', '段落', '和弦', '动态强弱', '事件'].map((label) => (
      <span className="timeline__track-label" key={label}>{label}</span>
    ))}
  </div>
  <div className="timeline__viewport" data-testid="timeline-viewport" ref={viewport.viewportRef}>
    <div
      className="timeline__content"
      data-testid="timeline-content"
      style={{ width: viewport.contentWidth > 0 ? `${viewport.contentWidth}px` : '100%' }}
    >
      <div className="timeline__overlay" aria-hidden="true">
        {selectionStyle ? <div className="timeline__selection" data-timeline-layer="selection" style={selectionStyle} /> : null}
        <div className="timeline__playhead" data-timeline-layer="playhead" style={{ left: `${timeToPercent(timeline.currentTime, timeline.duration)}%` }} />
      </div>
      <div className="timeline__track-content" data-timeline-layer="selection">{selectionSurface}</div>
      <div className="timeline__track-content" data-timeline-layer="waveform">{waveformTrack}</div>
      <div className="timeline__track-content" data-timeline-layer="sections">{sectionTrack}</div>
      <div className="timeline__track-content" data-timeline-layer="chords">{chordTrack}</div>
      <div className="timeline__track-content" data-timeline-layer="energy">{energyTrack}</div>
      <div className="timeline__track-content" data-timeline-layer="events">{eventTrack}</div>
    </div>
  </div>
</div>
```

在实际编辑中，`selectionSurface`、`waveformTrack`、`sectionTrack`、`chordTrack`、`energyTrack`、`eventTrack` 是 `Timeline` 内部在 `return` 前构造的六个 `ReactNode` 常量；它们逐段移动现有真实数据渲染，不创建演示数组。波形和动态 SVG 保持 `viewBox="0 0 100 100"`、`preserveAspectRatio="none"`，其 DOM 宽度继承 `.timeline__track-content`。

- [ ] **Step 5: 添加严格的段落与事件展示函数**

```ts
const SECTION_LABELS: Readonly<Record<string, string>> = {
  intro: '前奏',
  verse: '主歌',
  pre_chorus: '预副歌',
  chorus: '副歌',
  bridge: '桥段',
  outro: '尾奏',
}

export function sectionDisplayLabel(label: string): string {
  const trimmed = label.trim()
  if (!trimmed) return '未命名段落'
  return SECTION_LABELS[trimmed.toLowerCase()] ?? `段落 ${trimmed}`
}

export function energyEventLabel(event: EnergyChangeSummary): string {
  const direction = event.direction === 'rise' ? '动态上升' : '动态下降'
  return `${direction} ${formatTime(event.timestamp_seconds)}，强度 ${Math.round(event.magnitude * 100)}%`
}
```

段落按钮正文使用 `sectionDisplayLabel(section.label)`；事件按钮 `aria-label` 与可见摘要都使用 `energyEventLabel(event)`。缺失波形、段落、动态、事件时分别渲染 Task 2 测试中的四条空状态。

- [ ] **Step 6: 完成统一画布基础 CSS**

```css
.timeline__frame {
  display: grid;
  grid-template-columns: var(--timeline-label-width) minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.timeline__labels {
  z-index: 4;
  display: grid;
  grid-template-rows: repeat(6, minmax(3rem, auto));
  border-right: 1px solid var(--border);
  background: var(--surface);
}

.timeline__viewport {
  min-width: 0;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
}

.timeline__content {
  position: relative;
  min-width: 100%;
}

.timeline__track-content {
  position: relative;
  min-height: 3rem;
}

.timeline__track-content + .timeline__track-content,
.timeline__track-label + .timeline__track-label {
  border-top: 1px solid var(--border);
}

.timeline__overlay {
  position: absolute;
  z-index: 3;
  inset: 0;
  pointer-events: none;
}
```

- [ ] **Step 7: 运行 Timeline 回归并确认 GREEN**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/useTimelineViewport.test.tsx src/features/timeline/Timeline.test.tsx`

Expected: PASS，原有 seek、选区、低置信度过滤和手机列表测试继续通过。

- [ ] **Step 8: 提交统一画布**

```bash
git add frontend/src/features/timeline/Timeline.tsx frontend/src/features/timeline/Timeline.test.tsx frontend/src/styles/global.css
git commit -m "feat: scale timeline tracks on one canvas"
```

---

### Task 3: 播放头邻近的和弦与事件聚焦提示

**Files:**
- Modify: `frontend/src/features/timeline/Timeline.tsx:21-352`
- Modify: `frontend/src/features/timeline/Timeline.test.tsx`
- Modify: `frontend/src/styles/global.css:823-876`

**Interfaces:**
- Consumes: `timeline.currentTime`、可见和弦区间和真实 `energy_changes`。
- Produces: `isChordCurrent(chord, currentTime): boolean` 和 `isEventNear(timestamp, currentTime, windowSeconds = 0.75): boolean`。
- Produces: 和弦/事件上的 `data-current="true|false"`、文字提示与可见 focus ring；颜色不是唯一编码。

- [ ] **Step 1: 添加失败的当前事件测试**

```tsx
it('focuses the chord under the playhead and only nearby real energy events', () => {
  function CurrentHarness() {
    const timeline = useTimeline(richResult.track.duration_seconds)
    return (
      <>
        <button onClick={() => timeline.seek(6)} type="button">跳到六秒</button>
        <Timeline result={richResult} timeline={timeline} />
      </>
    )
  }
  render(<CurrentHarness />)
  fireEvent.click(screen.getByRole('button', { name: '跳到六秒' }))
  expect(screen.getByRole('button', { name: /和弦 C/ })).toHaveAttribute('data-current', 'true')
  expect(screen.getByText('正在经过 C 和弦')).toBeVisible()
  expect(screen.getByRole('button', { name: /动态上升 0:06/ })).toHaveAttribute('data-current', 'true')
  expect(screen.queryByText(/鼓组|主唱|乐器/)).not.toBeInTheDocument()
})

it('uses deterministic boundary helpers', () => {
  expect(isChordCurrent(richResult.chords[0], 8)).toBe(false)
  expect(isChordCurrent(richResult.chords[1], 8)).toBe(true)
  expect(isEventNear(6, 6.75)).toBe(true)
  expect(isEventNear(6, 6.76)).toBe(false)
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/Timeline.test.tsx`

Expected: FAIL，缺少聚焦 helper、`data-current` 和摘要。

- [ ] **Step 3: 实现边界与可读提示**

```ts
export function isChordCurrent(chord: ChordResult, currentTime: number): boolean {
  return currentTime >= chord.start_seconds && currentTime < chord.end_seconds
}

export function isEventNear(
  timestamp: number,
  currentTime: number,
  windowSeconds = 0.75,
): boolean {
  return Math.abs(timestamp - currentTime) <= windowSeconds
}
```

和弦按钮在当前区间时设置 `data-current="true"`，并在按钮内部增加 `<span className="timeline__event-hint">正在经过 {chord.symbol} 和弦</span>`。事件按钮在邻近窗口内设置 `data-current="true"`，内部摘要只使用 `energyEventLabel(event)`。非当前项不挂载 hint，避免屏幕阅读器重复朗读。

- [ ] **Step 4: 添加克制聚焦 CSS**

```css
.timeline__event--chord,
.timeline__marker {
  transition: transform 150ms ease, background-color 150ms ease, box-shadow 150ms ease;
}

.timeline__event--chord[data-current='true'],
.timeline__marker[data-current='true'] {
  z-index: 2;
  box-shadow: var(--focus-ring);
  transform: scale(1.04);
}

.timeline__event-hint {
  position: absolute;
  z-index: 5;
  bottom: calc(100% + var(--space-2));
  left: 50%;
  width: max-content;
  max-width: 14rem;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  box-shadow: var(--shadow-soft);
  color: var(--fg-2);
  font-size: 0.75rem;
  transform: translateX(-50%);
}
```

- [ ] **Step 5: 运行定向测试并提交**

Run: `npm.cmd --prefix frontend run test -- src/features/timeline/Timeline.test.tsx`

Expected: PASS。

```bash
git add frontend/src/features/timeline/Timeline.tsx frontend/src/features/timeline/Timeline.test.tsx frontend/src/styles/global.css
git commit -m "feat: focus timeline events at playhead"
```

---

### Task 4: 用户手势内的钢琴式单音试听

**Files:**
- Create: `frontend/src/features/chords/useToneAudition.ts`
- Create: `frontend/src/features/chords/useToneAudition.test.tsx`

**Interfaces:**
- Consumes: 后端已验证的 `pitch_classes` 音名字符串。
- Produces: `pitchClassFrequency(pitchClass: string, octave?: number): number | null`。
- Produces: `useToneAudition(): { audition(pitchClass: string): boolean; unavailable: boolean; stop(): void }`。
- Web Audio 发声总时长固定约 1.2 秒；关闭详情时停止 oscillator 并关闭 `AudioContext`。

- [ ] **Step 1: 添加失败的音名、发声与清理测试**

```tsx
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { pitchClassFrequency, useToneAudition } from './useToneAudition'

describe('useToneAudition', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('maps supported accidentals deterministically', () => {
    expect(pitchClassFrequency('A', 4)).toBeCloseTo(440, 4)
    expect(pitchClassFrequency('Bb', 4)).toBeCloseTo(466.1638, 3)
    expect(pitchClassFrequency('G##', 4)).toBeCloseTo(440, 4)
    expect(pitchClassFrequency('H', 4)).toBeNull()
  })

  it('starts one decaying tone and releases it on unmount', () => {
    const stop = vi.fn()
    const close = vi.fn()
    const oscillator = {
      addEventListener: vi.fn(),
      connect: vi.fn(),
      frequency: { setValueAtTime: vi.fn() },
      start: vi.fn(),
      stop,
      type: 'sine',
    }
    const gain = { connect: vi.fn(), gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() } }
    vi.stubGlobal('AudioContext', class {
      currentTime = 2
      destination = {}
      createOscillator = () => oscillator
      createGain = () => gain
      close = close
    })
    const { result, unmount } = renderHook(() => useToneAudition())
    act(() => expect(result.current.audition('C')).toBe(true))
    expect(oscillator.start).toHaveBeenCalledWith(2)
    expect(oscillator.stop).toHaveBeenCalledWith(3.2)
    unmount()
    expect(stop).toHaveBeenCalled()
    expect(close).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/useToneAudition.test.tsx`

Expected: FAIL，无法解析 `./useToneAudition`。

- [ ] **Step 3: 实现确定性音名映射和安全生命周期**

```ts
import { useCallback, useEffect, useRef, useState } from 'react'

const NOTE_INDEX: Readonly<Record<string, number>> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }

export function pitchClassFrequency(pitchClass: string, octave = 4): number | null {
  const match = /^([A-G])([#b]{0,2})$/.exec(pitchClass)
  if (!match || !Number.isInteger(octave)) return null
  const accidental = [...match[2]].reduce((sum, mark) => sum + (mark === '#' ? 1 : -1), 0)
  const midi = 12 * (octave + 1) + NOTE_INDEX[match[1]] + accidental
  return 440 * 2 ** ((midi - 69) / 12)
}

export function useToneAudition() {
  const contextRef = useRef<AudioContext | null>(null)
  const activeRef = useRef<OscillatorNode[]>([])
  const [unavailable, setUnavailable] = useState(false)

  const stop = useCallback(() => {
    activeRef.current.forEach((node) => { try { node.stop() } catch {} })
    activeRef.current = []
    const context = contextRef.current
    contextRef.current = null
    if (context) void context.close()
  }, [])

  useEffect(() => stop, [stop])

  const audition = useCallback((pitchClass: string): boolean => {
    const frequency = pitchClassFrequency(pitchClass)
    const Context = window.AudioContext
    if (frequency === null || !Context) {
      setUnavailable(true)
      return false
    }
    try {
      const context = contextRef.current ?? new Context()
      contextRef.current = context
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      const now = context.currentTime
      oscillator.type = 'triangle'
      oscillator.frequency.setValueAtTime(frequency, now)
      gain.gain.setValueAtTime(0.0001, now)
      gain.gain.exponentialRampToValueAtTime(0.28, now + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.2)
      oscillator.connect(gain)
      gain.connect(context.destination)
      oscillator.start(now)
      oscillator.stop(now + 1.2)
      activeRef.current.push(oscillator)
      oscillator.addEventListener('ended', () => {
        activeRef.current = activeRef.current.filter((node) => node !== oscillator)
      }, { once: true })
      setUnavailable(false)
      return true
    } catch {
      setUnavailable(true)
      return false
    }
  }, [])

  return { audition, unavailable, stop }
}
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/useToneAudition.test.tsx`

Expected: PASS。

- [ ] **Step 5: 提交试听层**

```bash
git add frontend/src/features/chords/useToneAudition.ts frontend/src/features/chords/useToneAudition.test.tsx
git commit -m "feat: add gesture-only chord tone audition"
```

---

### Task 5: 可连续操作的组成音轨道、浮层和钢琴反馈

**Files:**
- Create: `frontend/src/features/chords/ChordOrbit.tsx`
- Create: `frontend/src/features/chords/ChordPiano.tsx`
- Create: `frontend/src/features/chords/ChordOrbit.test.tsx`
- Modify: `frontend/src/styles/global.css:986-1010`

**Interfaces:**
- Consumes: `pitchClasses: string[]`、`intervals: string[]`、`selectedPitchClass: string | null`、`onActivate(pitchClass: string, interval: string): void`。
- Produces: `<ChordOrbit>`；悬停/焦点只暂停和显示 tooltip，点击/Enter/Space 才调用 `onActivate`。
- Produces: `<ChordPiano pitchClasses: string[] activePitchClass: string | null>`；不创建 `<audio>`。
- Produces: `intervalEducation(interval: string): { distance: string; character: string; memory: string }`。

```ts
export interface ChordOrbitProps {
  pitchClasses: string[]
  intervals: string[]
  selectedPitchClass: string | null
  onActivate: (pitchClass: string, interval: string) => void
}

export interface ChordPianoProps {
  pitchClasses: string[]
  activePitchClass: string | null
}
```

- [ ] **Step 1: 添加失败的连续激活与交互状态测试**

```tsx
it('lets C, E and G activate in sequence without an overlay stealing input', async () => {
  const user = userEvent.setup()
  const onActivate = vi.fn()
  const { container } = render(
    <ChordOrbit
      intervals={['root', 'major third', 'perfect fifth']}
      onActivate={onActivate}
      pitchClasses={['C', 'E', 'G']}
      selectedPitchClass={null}
    />,
  )
  for (const pitch of ['C', 'E', 'G']) await user.click(screen.getByRole('button', { name: new RegExp(`组成音 ${pitch}`) }))
  expect(onActivate.mock.calls.map(([pitch]) => pitch)).toEqual(['C', 'E', 'G'])
  expect(container.querySelector('.chord-orbit__rings')).toHaveStyle({ pointerEvents: 'none' })
  expect(container.querySelectorAll('.chord-orbit__note')).toHaveLength(3)
})

it('pauses on hover or focus, resumes on leave, and does not audition from hover', async () => {
  const user = userEvent.setup()
  const onActivate = vi.fn()
  render(
    <ChordOrbit intervals={['root', 'major third', 'perfect fifth']} onActivate={onActivate} pitchClasses={['C', 'E', 'G']} selectedPitchClass={null} />,
  )
  const e = screen.getByRole('button', { name: /组成音 E/ })
  await user.hover(e)
  expect(screen.getByTestId('chord-orbit')).toHaveAttribute('data-paused', 'true')
  expect(screen.getByRole('tooltip')).toHaveTextContent('大三度')
  expect(onActivate).not.toHaveBeenCalled()
  await user.unhover(e)
  expect(screen.getByTestId('chord-orbit')).toHaveAttribute('data-paused', 'false')
  e.focus()
  expect(screen.getByTestId('chord-orbit')).toHaveAttribute('data-paused', 'true')
})

it('marks the matching piano key without creating a second audio element', () => {
  const { container } = render(<ChordPiano activePitchClass="E" pitchClasses={['C', 'E', 'G']} />)
  expect(screen.getByRole('img', { name: 'C、E、G 的钢琴键位' })).toBeVisible()
  expect(container.querySelector('[data-pitch="E"]')).toHaveAttribute('data-active', 'true')
  expect(container.querySelectorAll('audio')).toHaveLength(0)
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/ChordOrbit.test.tsx`

Expected: FAIL，无法解析 `ChordOrbit` 和 `ChordPiano`。

- [ ] **Step 3: 实现组成音教学映射与 ChordOrbit 状态机**

```tsx
const INTERVAL_COPY: Readonly<Record<string, { name: string; distance: string; character: string; memory: string }>> = {
  root: { name: '根音', distance: '0 个半音', character: '稳定、明确', memory: '和弦名称的起点' },
  'major third': { name: '大三度', distance: '4 个半音', character: '明亮、开阔', memory: '从根音向上数四个半音' },
  'minor third': { name: '小三度', distance: '3 个半音', character: '柔和、内敛', memory: '从根音向上数三个半音' },
  'perfect fifth': { name: '纯五度', distance: '7 个半音', character: '稳定、有支撑', memory: '从根音向上数七个半音' },
}

export function intervalEducation(interval: string) {
  return INTERVAL_COPY[interval] ?? {
    name: interval,
    distance: '以当前和弦记录为准',
    character: '可与其他组成音对照聆听',
    memory: '记住它在当前和弦中的位置',
  }
}

export function ChordOrbit({ pitchClasses, intervals, selectedPitchClass, onActivate }: ChordOrbitProps) {
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const preview = previewIndex === null ? null : intervalEducation(intervals[previewIndex])
  return (
    <div className="chord-orbit" data-paused={previewIndex !== null} data-testid="chord-orbit">
      <div aria-hidden="true" className="chord-orbit__rings" style={{ pointerEvents: 'none' }} />
      {pitchClasses.map((pitch, index) => (
        <div className="chord-orbit__carrier" key={`${pitch}-${index}`} style={{ '--orbit-index': index } as CSSProperties}>
          <button
            aria-label={`组成音 ${pitch}，${intervalEducation(intervals[index]).name}`}
            aria-pressed={selectedPitchClass === pitch}
            className="chord-orbit__note"
            onBlur={() => setPreviewIndex(null)}
            onClick={() => onActivate(pitch, intervals[index])}
            onFocus={() => setPreviewIndex(index)}
            onMouseEnter={() => setPreviewIndex(index)}
            onMouseLeave={() => setPreviewIndex(null)}
            type="button"
          >
            {pitch}
          </button>
        </div>
      ))}
      {preview ? (
        <div className="chord-orbit__tooltip" role="tooltip">
          <strong>{preview.name}</strong>
          <span>{preview.distance} · {preview.character}</span>
        </div>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 4: 实现纯视觉 ChordPiano**

```tsx
const PIANO_KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] as const
const PITCH_INDEX: Readonly<Record<string, number>> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }

function canonicalPitchClass(pitch: string): string | null {
  const match = /^([A-G])([#b]{0,2})$/.exec(pitch)
  if (!match) return null
  const accidental = [...match[2]].reduce((total, mark) => total + (mark === '#' ? 1 : -1), 0)
  return PIANO_KEYS[(PITCH_INDEX[match[1]] + accidental + 12) % 12]
}

export function ChordPiano({ pitchClasses, activePitchClass }: ChordPianoProps) {
  const normalized = new Set(pitchClasses.map(canonicalPitchClass).filter((pitch): pitch is string => pitch !== null))
  const active = canonicalPitchClass(activePitchClass ?? '')
  return (
    <div aria-label={`${pitchClasses.join('、')} 的钢琴键位`} className="chord-piano" role="img">
      {PIANO_KEYS.map((pitch) => (
        <span
          className={`chord-piano__key${pitch.includes('#') ? ' chord-piano__key--black' : ''}`}
          data-active={active === pitch}
          data-chord-tone={normalized.has(pitch)}
          data-pitch={pitch}
          key={pitch}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 5: 实现轨道圆心、命中层和慢速动画 CSS**

```css
.chord-orbit {
  --orbit-size: min(25rem, 82vw);
  position: relative;
  width: var(--orbit-size);
  height: var(--orbit-size);
  max-width: 100%;
  margin-inline: auto;
  overflow: visible;
}

.chord-orbit__rings {
  position: absolute;
  inset: 8%;
  border: 1px solid var(--border);
  border-radius: 50%;
  box-shadow: inset 0 0 0 calc(var(--orbit-size) * .11) transparent,
    inset 0 0 0 calc(var(--orbit-size) * .11 + 1px) var(--border),
    inset 0 0 0 calc(var(--orbit-size) * .22) transparent,
    inset 0 0 0 calc(var(--orbit-size) * .22 + 1px) var(--border);
}

.chord-orbit__carrier {
  --orbit-phase: calc(var(--orbit-index) * 120deg);
  --orbit-radius: calc(var(--orbit-size) * (.18 + var(--orbit-index) * .09));
  position: absolute;
  z-index: 2;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  animation: chord-orbit-turn calc(34s + var(--orbit-index) * 7s) linear infinite;
  transform: rotate(var(--orbit-phase));
}

.chord-orbit__note {
  position: absolute;
  width: 3.25rem;
  height: 3.25rem;
  border: 1px solid var(--chord);
  border-radius: 50%;
  background: var(--surface);
  color: var(--chord);
  transform: translate(var(--orbit-radius), -50%) translateX(-50%);
  transition: width 150ms ease, height 150ms ease, background-color 150ms ease;
}

.chord-orbit[data-paused='true'] .chord-orbit__carrier,
.chord-orbit[data-paused='true'] .chord-orbit__note {
  animation-play-state: paused;
}

.chord-orbit__note:hover,
.chord-orbit__note:focus-visible,
.chord-orbit__note[aria-pressed='true'] {
  width: 3.75rem;
  height: 3.75rem;
  background: var(--accent-soft);
  color: var(--accent-strong);
}

@keyframes chord-orbit-turn {
  from { rotate: var(--orbit-phase); }
  to { rotate: calc(var(--orbit-phase) + 1turn); }
}
```

实现时使用 CSS individual transform property `rotate` 让 carrier 旋转，按钮的 `translate` 始终以自身圆心落在 `--orbit-radius` 上；`.chord-orbit__rings` 永久 `pointer-events:none`，tooltip 放在不裁剪的 `.chord-orbit` 直接子层并以 `max-width:min(18rem, calc(100vw - 2rem))` 限宽。

- [ ] **Step 6: 运行测试并提交**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/ChordOrbit.test.tsx`

Expected: PASS。

```bash
git add frontend/src/features/chords/ChordOrbit.tsx frontend/src/features/chords/ChordPiano.tsx frontend/src/features/chords/ChordOrbit.test.tsx frontend/src/styles/global.css
git commit -m "feat: add interactive chord tone orbit"
```

---

### Task 6: 组装真实性受限的和弦实验室详情会话

**Files:**
- Modify: `frontend/src/features/chords/ChordDetails.tsx:1-72`
- Modify: `frontend/src/features/chords/ChordDetails.test.tsx`
- Modify: `frontend/src/styles/global.css:604-639,986-1010`

**Interfaces:**
- Consumes: Task 4 的 `useToneAudition`，Task 5 的 `ChordOrbit`、`ChordPiano`、`intervalEducation`。
- Produces: 详情内部 `selectedTone: { pitchClass: string; interval: string } | null`；状态不提升到 workspace。
- Produces: 可靠 theory 的“通用乐理 / 构成 / 听感 / 情境”；不渲染 `algorithm`、`quality`、来源、后端扩展记录或歌曲上下文推断。

- [ ] **Step 1: 用失败测试锁定点击、重置和文案边界**

```tsx
it('previews on hover but only selects a tone after activation', async () => {
  const user = userEvent.setup()
  render(<ChordDetails chord={fixtureResult.chords[1]} />)
  expect(screen.getByText('选择一个组成音')).toBeVisible()
  const g = screen.getByRole('button', { name: /组成音 G/ })
  await user.hover(g)
  expect(screen.getByRole('tooltip')).toBeVisible()
  expect(screen.getByText('选择一个组成音')).toBeVisible()
  await user.click(g)
  expect(screen.getByRole('heading', { name: 'G · 根音' })).toBeVisible()
  expect(screen.getByText('音程距离')).toBeVisible()
  expect(screen.queryByText(/试听动作|在和弦中/)).not.toBeInTheDocument()
})

it('shows concise general theory without backend metadata', () => {
  render(<ChordDetails chord={fixtureResult.chords[1]} />)
  expect(screen.getByRole('heading', { name: '通用乐理' })).toBeVisible()
  for (const label of ['构成', '听感', '情境']) expect(screen.getByText(label)).toBeVisible()
  expect(screen.queryByText(/quality|算法|来源|后端|扩展记录|dominant|deterministic/)).not.toBeInTheDocument()
})

it('starts each mounted detail with an empty tone session', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<ChordDetails chord={fixtureResult.chords[1]} key="first" />)
  await user.click(screen.getByRole('button', { name: /组成音 B/ }))
  expect(screen.getByRole('heading', { name: 'B · 大三度' })).toBeVisible()
  rerender(<ChordDetails chord={fixtureResult.chords[1]} key="second" />)
  expect(screen.getByText('选择一个组成音')).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'B · 大三度' })).not.toBeInTheDocument()
  expect(document.querySelector('.chord-piano__key[data-active="true"]')).toBeNull()
})
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/ChordDetails.test.tsx`

Expected: FAIL，当前详情没有轨道、会话状态和通用乐理三栏。

- [ ] **Step 3: 组装详情状态与试听动作**

```tsx
const [selectedTone, setSelectedTone] = useState<{ pitchClass: string; interval: string } | null>(null)
const tone = useToneAudition()
const activateTone = (pitchClass: string, interval: string) => {
  setSelectedTone({ pitchClass, interval })
  tone.audition(pitchClass)
}

<ChordOrbit
  intervals={theory.intervals}
  onActivate={activateTone}
  pitchClasses={theory.pitch_classes}
  selectedPitchClass={selectedTone?.pitchClass ?? null}
/>
<ChordPiano
  activePitchClass={selectedTone?.pitchClass ?? null}
  pitchClasses={theory.pitch_classes}
/>
{tone.unavailable ? <p className="tone-audition-status" role="status">此设备暂不支持试听</p> : null}
<section aria-live="polite" className="tone-education">
  {selectedTone ? <ToneEducation pitchClass={selectedTone.pitchClass} interval={selectedTone.interval} /> : <p>选择一个组成音</p>}
</section>
```

`ToneEducation` 使用 `intervalEducation(interval)`，标题固定为 `{pitchClass} · {name}`，定义列表固定为“音程距离 / 听感提示 / 记忆方法”；根音不添加“试听动作”“在和弦中”等操作或系统措辞。

- [ ] **Step 4: 添加受限的通用乐理 copy**

```ts
const QUALITY_COPY = {
  major: {
    character: '明亮、稳定，常带有清晰的展开感。',
    context: '常用于建立明朗感、稳定感或清晰收束。',
  },
  minor: {
    character: '柔和、内敛，常带有含蓄的张力。',
    context: '常用于营造内省、克制或细腻的段落。',
  },
} as const
```

渲染 `<h3>通用乐理</h3>` 和三个事实：`构成 = pitch_classes.join(' · ')`、`听感 = QUALITY_COPY[quality].character`、`情境 = QUALITY_COPY[quality].context`。该区域不读取 `functions`、`roman_numeral`、`limitations`、`algorithm` 或歌曲 `track.mode`。

- [ ] **Step 5: 保留所有真实性降级**

当 `chord.symbol === 'unknown'`、`!isUsableConfidence(chord.confidence)` 或 `!chord.theory` 时，只渲染现有时间、标题和“暂无可用的和声细节”，不挂载 `ChordOrbit`、`ChordPiano` 或 `QUALITY_COPY`。

- [ ] **Step 6: 运行和弦测试并提交**

Run: `npm.cmd --prefix frontend run test -- src/features/chords/useToneAudition.test.tsx src/features/chords/ChordOrbit.test.tsx src/features/chords/ChordDetails.test.tsx`

Expected: PASS。

```bash
git add frontend/src/features/chords/ChordDetails.tsx frontend/src/features/chords/ChordDetails.test.tsx frontend/src/styles/global.css
git commit -m "feat: build truthful chord laboratory"
```

---

### Task 7: 桌面下方面板与手机/平板全屏详情

**Files:**
- Modify: `frontend/src/hooks/useMediaQuery.ts:1-21`
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.tsx:1-254`
- Modify: `frontend/src/features/workspace/AnalysisWorkspace.test.tsx`
- Modify: `frontend/src/styles/global.css:524-542,1360-1540`

**Interfaces:**
- Consumes: `FULLSCREEN_CHORD_DETAIL_QUERY = '(max-width: 1023px)'`。
- Produces: `isFullscreenDetail`；599px 的 `isMobile` 不再决定 portal/modal。
- Produces: 每次详情打开时新的 `<ChordDetails key={detailSession}>`；返回保持 `selectedChord` 和触发按钮焦点，但清空详情内部组成音状态。

- [ ] **Step 1: 将 viewport 测试工具扩为精确宽度并添加失败边界测试**

```tsx
function setViewportWidth(width: number) {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
    addEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
    matches:
      (query === '(max-width: 599px)' && width <= 599) ||
      (query === '(max-width: 1023px)' && width <= 1023),
    media: query,
    onchange: null,
    removeEventListener: vi.fn(),
  })))
}

it.each([
  [599, true, true],
  [600, false, true],
  [1023, false, true],
  [1024, false, false],
])('separates the mobile list and fullscreen detail at %ipx', async (width, mobileList, fullscreen) => {
  setViewportWidth(width)
  const user = userEvent.setup()
  const { container } = renderWorkspaceInAppShell()
  await screen.findByRole('heading', { name: 'Music DNA' })
  await user.click(screen.getByRole('button', { name: /结构地图/ }))
  expect(Boolean(screen.queryByRole('region', { name: '和弦事件列表' }))).toBe(mobileList)
  await user.click(screen.getByRole('button', { name: /和弦 G/ }).first())
  expect(Boolean(screen.queryByRole('dialog', { name: 'G 和弦' }))).toBe(fullscreen)
  expect(Boolean(screen.queryByRole('complementary', { name: '当前和弦详情' }))).toBe(!fullscreen)
  expect(container.querySelectorAll('audio')).toHaveLength(1)
})
```

- [ ] **Step 2: 添加失败的桌面顺序、会话重置和单次加载测试**

```tsx
it('places desktop detail below the complete timeline and resets only detail session state', async () => {
  setViewportWidth(1440)
  const user = userEvent.setup()
  const { container, loadResult } = renderWorkspace()
  await screen.findByRole('heading', { name: 'Music DNA' })
  await user.click(screen.getByRole('button', { name: /结构地图/ }))
  const chord = screen.getByRole('button', { name: /和弦 G/ })
  await user.click(chord)
  await user.click(screen.getByRole('button', { name: /组成音 B/ }))
  const timeline = container.querySelector('.timeline')
  const detail = container.querySelector('.workspace-detail')
  expect(timeline?.compareDocumentPosition(detail as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '返回结构地图' }))
  expect(chord).toHaveAttribute('aria-pressed', 'true')
  await user.click(chord)
  expect(screen.getByText('选择一个组成音')).toBeVisible()
  expect(container.querySelector('.chord-piano__key[data-active="true"]')).toBeNull()
  expect(container.querySelectorAll('audio')).toHaveLength(1)
  expect(loadResult).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 3: 运行测试并确认 RED**

Run: `npm.cmd --prefix frontend run test -- src/features/workspace/AnalysisWorkspace.test.tsx`

Expected: FAIL，600–1023px 仍为内联详情，桌面仍使用侧栏布局，详情会话没有显式 key。

- [ ] **Step 4: 新增详情断点并改造状态职责**

```ts
export const MOBILE_WORKSPACE_QUERY = '(max-width: 599px)'
export const FULLSCREEN_CHORD_DETAIL_QUERY = '(max-width: 1023px)'
```

```tsx
const isMobile = useMediaQuery(MOBILE_WORKSPACE_QUERY)
const isFullscreenDetail = useMediaQuery(FULLSCREEN_CHORD_DETAIL_QUERY)
const [detailSession, setDetailSession] = useState(0)
const fullscreenDetailOpen = isFullscreenDetail && detailOpen && selectedChord !== null

const openChord = (chord: ChordResult, trigger: HTMLButtonElement) => {
  lastChordTrigger.current = trigger
  restoreFocusAfterClose.current = false
  setSelectedChord(chord)
  setDetailSession((session) => session + 1)
  setDetailOpen(true)
}
```

把 modal 语义、焦点陷阱、`inert`、body lock 和 portal 的所有 `isMobile`/`mobileDetailOpen` 条件替换为 `isFullscreenDetail`/`fullscreenDetailOpen`。`Timeline` 仍单独使用 `isMobile`，因此 600–1023px 不出现手机和弦列表。

- [ ] **Step 5: 改为桌面纵向顺序并给详情会话稳定 key**

```tsx
<div className="workspace-map-layout">
  <Timeline
    onChordDeselect={clearChord}
    onChordSelect={openChord}
    result={result}
    selectedChord={selectedChord}
    timeline={timeline}
  />
  {!isFullscreenDetail ? chordDetail : null}
</div>
```

`chordDetail` 内使用 `<ChordDetails chord={selectedChord} key={`${selectedChord.id}-${detailSession}`} />`。关闭只执行 `setDetailOpen(false)`；`selectedChord` 保留供时间轴高亮和焦点恢复，详情组件因卸载而清空 selected tone、tooltip、按键与 Web Audio。

- [ ] **Step 6: 调整桌面与 1023px 全屏 CSS**

```css
.workspace-map-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-6);
}

.workspace-detail {
  min-width: 0;
  padding: var(--space-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}

@media (max-width: 1023px) {
  body.workspace-mobile-detail-open { overflow: hidden; }

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

从 `@media (max-width:599px)` 移除重复的 body lock 和 `.workspace-detail` fixed 规则；599px 断点只保留底部导航、手机列表和紧凑尺寸职责。

- [ ] **Step 7: 运行 workspace 与播放器回归并提交**

Run: `npm.cmd --prefix frontend run test -- src/features/workspace/AnalysisWorkspace.test.tsx src/features/player/AudioPlayer.test.tsx`

Expected: PASS；四个断点、单 audio、单次 load、返回焦点和状态重置全部通过。

```bash
git add frontend/src/hooks/useMediaQuery.ts frontend/src/features/workspace/AnalysisWorkspace.tsx frontend/src/features/workspace/AnalysisWorkspace.test.tsx frontend/src/styles/global.css
git commit -m "feat: make chord detail responsive by device class"
```

---

### Task 8: 动效降级、浏览器 E2E 与全量交付验证

**Files:**
- Modify: `frontend/src/styles/global.css:1542-1551`
- Modify: `e2e/responsive.spec.ts:1-130`
- Modify: `docs/superpowers/specs/2026-08-24-chord-lab-timeline-interactions-design.md:3`

**Interfaces:**
- Consumes: Tasks 1–7 的最终 DOM、ARIA 和 CSS 契约。
- Produces: Playwright 验收：五轨同宽同步缩放、播放头锚定、C/E/G 连续选择、悬停不裁剪、599/600/1023/1024 详情边界、返回重置、reduced motion、单 audio 与无页面溢出。

- [ ] **Step 1: 添加 reduced-motion 明确覆盖**

```css
@media (prefers-reduced-motion: reduce) {
  .chord-orbit__carrier,
  .chord-orbit__note {
    animation: none !important;
  }

  .timeline__event--chord,
  .timeline__marker,
  .chord-piano__key,
  .workspace-detail {
    transition: none !important;
  }
}
```

- [ ] **Step 2: 扩充 Playwright 响应式测试**

```ts
await page.getByRole('button', { name: /结构地图/ }).click()
const viewport = page.getByTestId('timeline-viewport')
const content = page.getByTestId('timeline-content')
const before = await content.boundingBox()
await page.getByRole('slider', { name: '时间轴缩放' }).fill('2.25')
const after = await content.boundingBox()
expect(before).not.toBeNull()
expect(after).not.toBeNull()
expect(after!.width / before!.width).toBeCloseTo(2.25, 1)
for (const layer of ['waveform', 'sections', 'chords', 'energy', 'events']) {
  await expect(content.locator(`[data-timeline-layer="${layer}"]`)).toHaveCSS('width', `${after!.width}px`)
}
expect(await viewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)

const chord = page.getByRole('button', { name: /和弦 G/ }).first()
await chord.click()
for (const pitch of ['G', 'B', 'D']) {
  await page.getByRole('button', { name: new RegExp(`组成音 ${pitch}`) }).click()
  await expect(page.locator('.chord-piano__key[data-active="true"]')).toHaveAttribute('data-pitch', pitch)
}
await page.getByRole('button', { name: '返回结构地图' }).click()
await chord.click()
await expect(page.getByText('选择一个组成音')).toBeVisible()
await expect(page.locator('.chord-piano__key[data-active="true"]')).toHaveCount(0)
await expect(page.locator('audio')).toHaveCount(1)
```

按 viewport 数组 `{599, 600, 1023, 1024, 1440}` 断言：宽度小于等于 1023 时是 `dialog[aria-modal=true]`，1024 和 1440 时是非 modal `complementary` 且其 bounding box 的 `y` 大于 `.timeline` 底部；仅 599 出现“和弦事件列表”。每个宽度继续执行 `document.documentElement.scrollWidth <= window.innerWidth`，横向溢出只能存在于 `.timeline__viewport`。

- [ ] **Step 3: 增加 reduced motion 浏览器场景**

```ts
await page.emulateMedia({ reducedMotion: 'reduce' })
await page.getByRole('button', { name: /结构地图/ }).click()
await page.getByRole('button', { name: /和弦 G/ }).first().click()
const carrier = page.locator('.chord-orbit__carrier').first()
await expect(carrier).toHaveCSS('animation-name', 'none')
await page.getByRole('button', { name: /组成音 G/ }).click()
await expect(page.getByRole('heading', { name: 'G · 根音' })).toBeVisible()
```

- [ ] **Step 4: 运行全部前端测试、类型检查和生产构建**

Run: `npm.cmd --prefix frontend run test`

Expected: PASS，所有 Vitest tests passed。

Run: `npm.cmd --prefix frontend run typecheck`

Expected: exit 0，无 TypeScript diagnostics。

Run: `npm.cmd --prefix frontend run build`

Expected: exit 0，Vite production build 完成。

Run: `npm.cmd run typecheck`

Expected: exit 0，E2E TypeScript diagnostics 为空。

- [ ] **Step 5: 使用独立 Docker 项目运行完整 E2E**

在运行前执行 `docker ps --format '{{.Names}}'`，选择未被其他任务使用的项目名 `museecho-chord-lab-e2e`。使用该项目名构建/启动当前 worktree，绝不执行无项目限定的 `docker compose down`。

Run: `$env:COMPOSE_PROJECT_NAME='museecho-chord-lab-e2e'; docker compose up -d --build`

Expected: 当前 worktree 的独立 app/gateway 容器 healthy；容器名称均以 `museecho-chord-lab-e2e` 开头。

Run: `npm.cmd run e2e`

Expected: PASS，真实上传、分析、响应式、PWA、安全和删除场景全部通过；没有 503、浏览器 console error 或 500 response。

Run: `$env:COMPOSE_PROJECT_NAME='museecho-chord-lab-e2e'; docker compose down --volumes`

Expected: 只停止并移除 `museecho-chord-lab-e2e` 项目的容器、网络和卷；其他任务容器保持运行。

- [ ] **Step 6: 真实浏览器视觉核验**

在 1440×900、1024×768、768×1024、390×844 下逐一检查：波形与动态曲线同步缩放；段落大区块和事件文字真实；桌面详情位于时间轴下方；平板/手机详情覆盖全屏；组成音 tooltip 不被圆形边界裁剪；悬停暂停、移开恢复；连续点击三个音均响应；返回重进为空；页面无水平溢出；浏览器控制台无错误。

- [ ] **Step 7: 最终提交**

```bash
git add frontend/src/styles/global.css e2e/responsive.spec.ts docs/superpowers/specs/2026-08-24-chord-lab-timeline-interactions-design.md
git commit -m "test: verify chord lab responsive interactions"
```

---

## Completion checklist

- [ ] 桌面详情在结构地图下方，页面可继续向下滚动；600–1023px 与手机均为全屏详情。
- [ ] 599px 手机和弦列表职责未扩展到 600px；599/600/1023/1024 边界均有自动测试。
- [ ] 页面只有一个歌曲 `<audio>`，详情打开不触发新的结果请求。
- [ ] 统一画布下的波形、段落、和弦、动态、事件、选区和播放头同时缩放且时间对齐。
- [ ] 缩放围绕播放头锚定，首尾钳制，非法时长时禁用。
- [ ] 后端 `A/B/C` 不被推断为主歌/副歌；事件不出现乐器或演唱语义。
- [ ] C/E/G 或 G/B/D 可连续点击；装饰轨道不拦截指针；浮层不被圆形容器裁剪。
- [ ] 悬停/焦点暂停并预览，离开恢复；只有点击/键盘激活才试听和更新下方详情。
- [ ] 返回再进入后组成音、tooltip、钢琴按键和说明为空，时间轴和弦高亮与焦点恢复保留。
- [ ] unknown、低置信度、缺失 theory、无 Web Audio、空数据和 reduced motion 均有真实降级。
- [ ] `DESIGN.md` 的语义颜色、Warm Editorial 层级、可见焦点和克制动效通过视觉核验。
- [ ] 定向测试、全量 Vitest、前端 typecheck/build、E2E typecheck 和独立 Docker 全量 E2E 全部通过。
