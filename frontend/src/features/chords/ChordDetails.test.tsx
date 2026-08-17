import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { ChordDetails } from './ChordDetails'

describe('ChordDetails', () => {
  it('renders selected chord theory without implementation metadata', () => {
    render(<ChordDetails chord={fixtureResult.chords[1]} />)

    expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
    expect(screen.getByText('G · B · D')).toBeVisible()
    expect(screen.getByText('大三和弦')).toBeVisible()
    expect(screen.queryByText('调内级数')).not.toBeInTheDocument()
    expect(screen.queryByText('可能功能')).not.toBeInTheDocument()
    expect(screen.getByText(/A–G 表示音名/)).toBeVisible()
    expect(screen.queryByText(/deterministic-triad-theory-v1/)).not.toBeInTheDocument()
  })

  it('keeps unknown chords unknown instead of deriving theory in the UI', () => {
    render(
      <ChordDetails
        chord={{ ...fixtureResult.chords[0], symbol: 'unknown', theory: null }}
      />,
    )

    expect(screen.getByText(/暂无可用的和声细节/)).toBeVisible()
    expect(screen.queryByText(/组成音|调内级数|功能/)).not.toBeInTheDocument()
  })

  it('withholds persisted theory when the chord confidence is low', () => {
    render(
      <ChordDetails chord={{ ...fixtureResult.chords[1], confidence: 0.2 }} />,
    )

    expect(screen.getByText(/暂无可用的和声细节/)).toBeVisible()
    expect(screen.queryByText('G · B · D')).not.toBeInTheDocument()
  })
})
