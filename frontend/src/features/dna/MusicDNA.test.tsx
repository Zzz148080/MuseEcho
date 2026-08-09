import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { MusicDNA } from './MusicDNA'

describe('MusicDNA', () => {
  it('shows only current analysis facts and their source', () => {
    render(<MusicDNA result={fixtureResult} />)

    expect(screen.getByText('120 BPM')).toBeVisible()
    expect(screen.getByText(/C 大调/)).toBeVisible()
    expect(screen.getByText('合成测试数据')).toBeVisible()
    expect(screen.getByText('0:12')).toBeVisible()
    expect(screen.queryByText(/情绪|风格|核心乐器/)).not.toBeInTheDocument()
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
    expect(
      screen.getAllByText('证据不足').filter(
        (item) => item.getAttribute('data-confidence') === 'unknown',
      ),
    ).toHaveLength(2)
  })
})
