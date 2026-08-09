import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { ChordDetails } from './ChordDetails'

describe('ChordDetails', () => {
  it('renders only persisted deterministic theory for the selected chord', () => {
    render(<ChordDetails chord={fixtureResult.chords[1]} />)

    expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
    expect(screen.getByText('G · B · D')).toBeVisible()
    expect(screen.getByText(/V/)).toBeVisible()
    expect(screen.getByText(/属功能/)).toBeVisible()
    expect(screen.getByText(/deterministic-triad-theory-v1/)).toBeVisible()
  })

  it('keeps unknown chords unknown instead of deriving theory in the UI', () => {
    render(
      <ChordDetails
        chord={{ ...fixtureResult.chords[0], symbol: 'unknown', theory: null }}
      />,
    )

    expect(screen.getByText(/证据不足/)).toBeVisible()
    expect(screen.queryByText(/组成音|调内级数|功能/)).not.toBeInTheDocument()
  })

  it('withholds persisted theory when the chord confidence is low', () => {
    render(
      <ChordDetails chord={{ ...fixtureResult.chords[1], confidence: 0.2 }} />,
    )

    expect(screen.getByText(/证据不足/)).toBeVisible()
    expect(screen.queryByText('G · B · D')).not.toBeInTheDocument()
  })
})
