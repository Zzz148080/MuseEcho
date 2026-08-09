import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResult } from '../../api/types'
import { fixtureResult as richResult } from '../../test/analysisFixture'
import { Timeline } from './Timeline'
import { clientXToSeconds } from './Timeline'
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
  it('seeking a chord moves the shared playhead to its start', async () => {
    const user = userEvent.setup()
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')

    await user.click(screen.getByRole('button', { name: /和弦 G/ }))

    expect(media?.currentTime).toBe(8)
    expect(screen.getByTestId('playhead')).toHaveAttribute('data-seconds', '8')
  })

  it('exposes waveform, section, chord, energy and event tracks as text-labelled groups', () => {
    render(<RichHarness />)

    for (const name of ['波形', '段落', '和弦', '能量', '重要事件']) {
      expect(screen.getByRole('group', { name: `${name}轨道` })).toBeVisible()
    }
    expect(screen.getByLabelText(/段落 A/)).toBeVisible()
    expect(screen.getByRole('button', { name: /能量上升/ })).toBeVisible()
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
    expect(screen.getByText(/尚未选择片段/)).toBeVisible()
  })

  it('renders a low-confidence chord as unknown on every event path', () => {
    const lowResult = {
      ...richResult,
      chords: [{ ...richResult.chords[1], confidence: 0.2 }],
    }
    function LowHarness() {
      const timeline = useTimeline(lowResult.track.duration_seconds)
      return <Timeline result={lowResult} timeline={timeline} />
    }
    render(<LowHarness />)

    expect(screen.getByRole('button', { name: /和弦 unknown/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /和弦 G/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByText(/时间轴文本事件列表/))
    expect(screen.getByText(/跳到 0:08 的unknown/)).toBeVisible()
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
