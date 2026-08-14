import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { MusicDNA } from './MusicDNA'

describe('MusicDNA', () => {
  it('shows listener-facing facts without internal source or event-count metadata', () => {
    render(<MusicDNA result={fixtureResult} />)

    expect(screen.getByText('120 BPM')).toBeVisible()
    expect(screen.getByText(/C 大调/)).toBeVisible()
    expect(screen.getByText('0:12')).toBeVisible()
    expect(screen.queryByText('合成测试数据')).not.toBeInTheDocument()
    expect(screen.queryByText(/和声摘要|结构摘要|可用和弦事件|可用段落/)).not.toBeInTheDocument()
    expect(screen.queryByText(/风格|核心乐器/)).not.toBeInTheDocument()
    expect(screen.getByText('平均音频强度')).toBeVisible()
    expect(screen.getByText(/不代表情绪或氛围/)).toBeVisible()
  })

  it('does not present a low-confidence value as a music fact', () => {
    render(
      <MusicDNA
        result={{
          ...fixtureResult,
          track: {
            ...fixtureResult.track,
            bpm: 180,
            bpm_confidence: 0.2,
            key_tonic: null,
            mode: null,
            key_confidence: null,
          },
        }}
      />,
    )

    expect(screen.queryByText('180 BPM')).not.toBeInTheDocument()
    expect(screen.queryByText('4 个')).not.toBeInTheDocument()
    expect(screen.getAllByText('暂未判定')).toHaveLength(3)
    expect(screen.queryByText('证据不足')).not.toBeInTheDocument()
  })

  it('shows a backend-accepted tentative tempo instead of discarding it', () => {
    render(
      <MusicDNA
        result={{
          ...fixtureResult,
          track: {
            ...fixtureResult.track,
            bpm: 86.13,
            bpm_confidence: 0.53,
          },
        }}
      />,
    )

    expect(screen.getByText('86 BPM')).toBeVisible()
    expect(screen.getByText('低置信')).toBeVisible()
  })
})
