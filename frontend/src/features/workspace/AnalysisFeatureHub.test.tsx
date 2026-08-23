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
