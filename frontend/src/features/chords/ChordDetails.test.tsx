import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import { ChordDetails } from './ChordDetails'

describe('ChordDetails', () => {
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
    for (const label of ['构成', '听感', '情境']) {
      expect(screen.getByText(label)).toBeVisible()
    }
    expect(
      screen.queryByText(
        /quality|算法|来源|后端|扩展记录|dominant|deterministic/,
      ),
    ).not.toBeInTheDocument()
  })

  it('starts every mounted detail with an empty tone session', async () => {
    const user = userEvent.setup()
    const { container, rerender } = render(
      <ChordDetails chord={fixtureResult.chords[1]} key="first" />,
    )
    await user.click(screen.getByRole('button', { name: /组成音 B/ }))
    expect(screen.getByRole('heading', { name: 'B · 大三度' })).toBeVisible()

    rerender(<ChordDetails chord={fixtureResult.chords[1]} key="second" />)

    expect(screen.getByText('选择一个组成音')).toBeVisible()
    expect(
      screen.queryByRole('heading', { name: 'B · 大三度' }),
    ).not.toBeInTheDocument()
    expect(
      container.querySelector('.chord-piano__key[data-active="true"]'),
    ).toBeNull()
  })

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
