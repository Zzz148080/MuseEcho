import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisResult } from '../../api/types'
import { fixtureResult as richResult } from '../../test/analysisFixture'
import { Timeline } from './Timeline'
import {
  clientXToSeconds,
  isChordCurrent,
  isEventNear,
  sectionDisplayLabel,
} from './Timeline'
import { timeToPercent, useTimeline } from './useTimeline'

const analysisId = '00000000-0000-4000-8000-000000000001'
const fixtureResult: AnalysisResult = {
  analysis_id: analysisId,
  source_kind: 'synthetic_test',
  pipeline_version: 'museecho-analysis-v1',
  track: {
    duration_seconds: 12,
    sample_rate: 44_100,
    channels: 1,
    bpm: 120,
    bpm_confidence: 0.91,
    key_tonic: 'C',
    mode: 'major',
    key_confidence: 0.88,
    time_signature: null,
    time_signature_confidence: null,
    summary: {
      source_kind: 'synthetic_test',
      pipeline_version: 'museecho-analysis-v1',
      signal_version: 'signal-features-v1',
      waveform: {
        resolution_seconds: 3,
        minimums: [-0.8, -0.4, -0.7, -0.3],
        maximums: [0.7, 0.5, 0.9, 0.4],
        algorithm: 'waveform-minmax-v1',
      },
      beat_positions_seconds: [0, 0.5, 1, 1.5],
      energy_changes: [],
    },
  },
  sections: [
    {
      id: '00000000-0000-4000-8000-000000000011',
      start_seconds: 0,
      end_seconds: 12,
      label: 'A',
      confidence: 0.9,
      algorithm: 'structure-v1',
    },
  ],
  chords: [
    {
      id: '00000000-0000-4000-8000-000000000021',
      start_seconds: 0,
      end_seconds: 8,
      symbol: 'C',
      confidence: 0.92,
      algorithm: 'chords-v1',
      theory: null,
    },
    {
      id: '00000000-0000-4000-8000-000000000022',
      start_seconds: 8,
      end_seconds: 12,
      symbol: 'G',
      confidence: 0.89,
      algorithm: 'chords-v1',
      theory: null,
    },
  ],
  time_series: [
    {
      kind: 'energy',
      resolution_seconds: 3,
      points: [0.2, 0.5, 0.8, 0.4],
      algorithm: 'rms-v1',
    },
  ],
  evidence: [],
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function setMobileViewport(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: query === '(max-width: 599px)' && matches,
      media: query,
      onchange: null,
      removeEventListener: vi.fn(),
    })),
  )
}

function Harness() {
  const timeline = useTimeline(fixtureResult.track.duration_seconds)
  return (
    <>
      <audio ref={timeline.mediaRef} />
      <Timeline result={fixtureResult} timeline={timeline} />
    </>
  )
}

function RichHarness() {
  const timeline = useTimeline(richResult.track.duration_seconds)
  return (
    <>
      <audio ref={timeline.mediaRef} />
      <Timeline result={richResult} timeline={timeline} />
    </>
  )
}

describe('Timeline', () => {
  it('keeps every musical layer on one scalable canvas without inventing semantics', () => {
    const { container } = render(<RichHarness />)
    const content = screen.getByTestId('timeline-content')

    expect(container.querySelectorAll('.timeline__content')).toHaveLength(1)
    expect(content.querySelectorAll('[data-timeline-layer]')).toHaveLength(7)
    expect(screen.getByText('段落 A')).toBeVisible()
    expect(screen.getByText('段落 B')).toBeVisible()
    expect(screen.queryByText('主歌')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '动态上升 0:06，强度 40%' }),
    ).toBeVisible()
    expect(screen.queryByText(/鼓组|主唱|乐器/)).not.toBeInTheDocument()
  })

  it('translates only explicit semantic section labels', () => {
    expect(sectionDisplayLabel('verse')).toBe('主歌')
    expect(sectionDisplayLabel('CHORUS')).toBe('副歌')
    expect(sectionDisplayLabel('A')).toBe('段落 A')
    expect(sectionDisplayLabel('')).toBe('未命名段落')
  })

  it('shows independent truthful empty states for missing tracks', () => {
    const emptyResult: AnalysisResult = {
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

  it('applies zoom to the one shared canvas', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(private readonly callback: ResizeObserverCallback) {}
        observe() {
          this.callback([], this as unknown as ResizeObserver)
        }
        disconnect() {}
      },
    )
    render(<RichHarness />)

    fireEvent.change(screen.getByRole('slider', { name: '时间轴缩放' }), {
      target: { value: '2.25' },
    })

    expect(screen.getByText('2.25×')).toBeVisible()
    expect(screen.getByTestId('timeline-content')).toHaveStyle({ width: '1800px' })
  })

  it('focuses only the chord and real energy event under the playhead', () => {
    function CurrentHarness() {
      const timeline = useTimeline(richResult.track.duration_seconds)
      return (
        <>
          <button onClick={() => timeline.seek(6)} type="button">
            跳到六秒
          </button>
          <Timeline result={richResult} timeline={timeline} />
        </>
      )
    }
    render(<CurrentHarness />)
    fireEvent.click(screen.getByRole('button', { name: '跳到六秒' }))

    const currentChord = screen.getByRole('button', {
      name: /和弦 C.*正在经过/,
    })
    expect(currentChord).toHaveAttribute('data-current', 'true')
    expect(currentChord).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText('正在经过 C 和弦')).toBeVisible()
    const currentEvent = screen.getByRole('button', {
      name: /动态上升 0:06.*正在经过/,
    })
    expect(currentEvent).toHaveAttribute('data-current', 'true')
    expect(currentEvent).toHaveAttribute('aria-current', 'true')
  })

  it('uses deterministic chord and event focus boundaries', () => {
    expect(isChordCurrent(richResult.chords[0], 8)).toBe(false)
    expect(isChordCurrent(richResult.chords[1], 8)).toBe(true)
    expect(isEventNear(6, 6.75)).toBe(true)
    expect(isEventNear(6, 6.76)).toBe(false)
  })

  it('seeking a chord moves the shared playhead to its start', async () => {
    const user = userEvent.setup()
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')

    await user.click(screen.getByRole('button', { name: /和弦 G/ }))

    expect(media?.currentTime).toBe(8)
    expect(screen.getByTestId('playhead')).toHaveAttribute('data-seconds', '8')
  })

  it('marks the selected chord and returns its activating button', async () => {
    const user = userEvent.setup()
    const onChordSelect = vi.fn()
    function SelectionHarness() {
      const timeline = useTimeline(richResult.track.duration_seconds)
      return (
        <Timeline
          onChordSelect={onChordSelect}
          result={richResult}
          selectedChord={richResult.chords[0]}
          timeline={timeline}
        />
      )
    }

    render(<SelectionHarness />)
    await user.click(screen.getByRole('button', { name: /和弦 C/ }))

    expect(screen.getByRole('button', { name: /和弦 C/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(onChordSelect).toHaveBeenCalledWith(
      richResult.chords[0],
      expect.any(HTMLButtonElement),
    )
  })

  it('keeps real tracks and presents safe section and energy labels', () => {
    render(<RichHarness />)

    for (const name of ['波形', '段落', '和弦', '动态强弱', '重要事件']) {
      expect(screen.getByRole('group', { name: `${name}轨道` })).toBeVisible()
    }
    expect(screen.getAllByTestId('section-boundary')).toHaveLength(richResult.sections.length)
    expect(screen.queryByText('A', { selector: '.timeline__event--section' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /动态上升/ })).toBeVisible()
  })

  it('turns a visual section boundary into its exact listening selection', async () => {
    const user = userEvent.setup()
    const { container } = render(<RichHarness />)
    const section = richResult.sections[0]
    const media = container.querySelector('audio')

    await user.click(screen.getAllByTestId('section-boundary')[0])

    expect(media?.currentTime).toBe(section.start_seconds)
    expect(screen.getByTestId('selection')).toHaveAttribute('data-start', String(section.start_seconds))
    expect(screen.getByTestId('selection')).toHaveAttribute('data-end', String(section.end_seconds))
  })

  it('keeps a backend-accepted short harmonic candidate visible and interactive', async () => {
    const lowResult = {
      ...richResult,
      chords: [
        ...richResult.chords,
        {
          ...richResult.chords[1],
          id: '00000000-0000-4000-8000-000000000023',
          symbol: 'unknown',
          confidence: 0,
          theory: null,
        },
        {
          ...richResult.chords[1],
          id: '00000000-0000-4000-8000-000000000024',
          start_seconds: 9,
          end_seconds: 10,
          symbol: 'A#',
          confidence: 0.94,
          theory: null,
        },
      ],
    }
    function FilteredHarness() {
      const timeline = useTimeline(lowResult.track.duration_seconds)
      return (
        <>
          <audio ref={timeline.mediaRef} />
          <Timeline result={lowResult} timeline={timeline} />
        </>
      )
    }

    const user = userEvent.setup()
    const { container } = render(<FilteredHarness />)
    const media = container.querySelector('audio')

    expect(screen.getAllByTestId('section-boundary')).toHaveLength(lowResult.sections.length)
    expect(screen.getByRole('button', { name: /段落 A/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /和弦 G/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /unknown/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /和弦 A#/ }))
    expect(media?.currentTime).toBe(9)
    expect(screen.getByTestId('playhead')).toHaveAttribute('data-seconds', '9')
    expect(screen.queryByText(/时间轴文本事件列表/)).not.toBeInTheDocument()
  })

  it('offers mobile chord events as chronological non-overlapping 44px controls', async () => {
    setMobileViewport(true)
    const user = userEvent.setup()
    const onChordSelect = vi.fn()
    function MobileHarness() {
      const timeline = useTimeline(richResult.track.duration_seconds)
      return (
        <Timeline
          onChordSelect={onChordSelect}
          result={richResult}
          selectedChord={richResult.chords[1]}
          timeline={timeline}
        />
      )
    }

    const { container } = render(<MobileHarness />)
    const list = screen.getByRole('region', { name: '和弦事件列表' })
    const controls = screen.getAllByRole('button', { name: /和弦 [CG]/ })

    expect(list).toBeVisible()
    expect(controls.map((control) => control.getAttribute('aria-label'))).toEqual([
      '和弦 C，0:00 至 0:08，高置信，正在经过',
      '和弦 G，0:08 至 0:12，高置信',
    ])
    expect(controls[0]).toHaveAttribute('aria-current', 'true')
    expect(controls[1]).not.toHaveAttribute('aria-current')
    expect(controls.every((control) => control.classList.contains('timeline__chord-list-button'))).toBe(true)
    expect(container.querySelectorAll('button.timeline__event--chord')).toHaveLength(0)
    expect(controls[1]).toHaveAttribute('aria-pressed', 'true')

    await user.click(controls[0])
    expect(onChordSelect).toHaveBeenCalledWith(
      richResult.chords[0],
      controls[0],
    )
  })

  it('supports keyboard seeking through the shared playhead', async () => {
    const user = userEvent.setup()
    const { container } = render(<RichHarness />)
    const seek = screen.getByRole('slider', { name: /播放位置/ })
    const media = container.querySelector('audio')

    await user.click(seek)
    await user.keyboard('{ArrowRight}')

    expect(media?.currentTime).toBe(5)
    expect(screen.getByTestId('playhead')).toHaveAttribute('data-seconds', '5')
  })

  it('turns a pointer drag into a clamped observable selection', () => {
    render(<RichHarness />)
    const surface = screen.getByTestId('selection-surface')
    vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
      bottom: 200,
      height: 100,
      left: 100,
      right: 500,
      toJSON: () => ({}),
      top: 100,
      width: 400,
      x: 100,
      y: 100,
    })

    fireEvent.pointerDown(surface, { button: 0, clientX: 200 })
    fireEvent.pointerMove(surface, { clientX: 400 })
    fireEvent.pointerUp(surface, { clientX: 400 })

    expect(screen.getByTestId('selection')).toHaveAttribute('data-start', '3')
    expect(screen.getByTestId('selection')).toHaveAttribute('data-end', '9')
    expect(screen.getByText(/已选 0:03–0:09/)).toBeVisible()
  })

  it('offers keyboard-native selection endpoints and a clear action', () => {
    render(<RichHarness />)

    fireEvent.change(screen.getByRole('slider', { name: '片段开始' }), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByRole('slider', { name: '片段结束' }), {
      target: { value: '10' },
    })

    expect(screen.getByText(/已选 0:02–0:10/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '清除选区' }))
    expect(screen.getByText(/选择片段以回听和比较/, { selector: '.timeline__text-summary' })).toBeVisible()
  })

  it('does not present a low-confidence chord as a harmonic candidate', () => {
    const lowResult = {
      ...richResult,
      chords: [{ ...richResult.chords[1], confidence: 0.2 }],
    }
    function LowHarness() {
      const timeline = useTimeline(lowResult.track.duration_seconds)
      return <Timeline result={lowResult} timeline={timeline} />
    }
    render(<LowHarness />)

    expect(screen.getByText('暂无局部和声候选')).toBeVisible()
    expect(screen.queryByRole('button', { name: /和弦 G/ })).not.toBeInTheDocument()
  })

  it('clamps coordinate conversion without creating non-finite positions', () => {
    expect(timeToPercent(-1, 10)).toBe(0)
    expect(timeToPercent(15, 10)).toBe(100)
    expect(timeToPercent(2, 0)).toBe(0)
    expect(clientXToSeconds(50, 100, 400, 12)).toBe(0)
    expect(clientXToSeconds(600, 100, 400, 12)).toBe(12)
    expect(clientXToSeconds(200, 100, 400, 12)).toBe(3)
  })
})
