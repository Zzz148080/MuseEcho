import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChordOrbit, intervalEducation } from './ChordOrbit'
import { ChordPiano } from './ChordPiano'

describe('ChordOrbit', () => {
  it('lets every composition tone activate in sequence without rings stealing input', async () => {
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

    for (const pitch of ['C', 'E', 'G']) {
      await user.click(
        screen.getByRole('button', { name: new RegExp(`组成音 ${pitch}`) }),
      )
    }

    expect(onActivate.mock.calls.map(([pitch]) => pitch)).toEqual([
      'C',
      'E',
      'G',
    ])
    expect(container.querySelector('.chord-orbit__rings')).toHaveStyle({
      pointerEvents: 'none',
    })
    expect(container.querySelectorAll('.chord-orbit__note')).toHaveLength(3)
  })

  it('pauses and previews on hover, resumes on leave, and does not activate', async () => {
    const user = userEvent.setup()
    const onActivate = vi.fn()
    render(
      <ChordOrbit
        intervals={['root', 'major third', 'perfect fifth']}
        onActivate={onActivate}
        pitchClasses={['C', 'E', 'G']}
        selectedPitchClass={null}
      />,
    )
    const e = screen.getByRole('button', { name: /组成音 E/ })

    await user.hover(e)
    expect(screen.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('大三度')
    expect(onActivate).not.toHaveBeenCalled()

    await user.unhover(e)
    expect(screen.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'false',
    )
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('offers the same pause and preview from keyboard focus', () => {
    render(
      <ChordOrbit
        intervals={['root', 'major third', 'perfect fifth']}
        onActivate={() => undefined}
        pitchClasses={['C', 'E', 'G']}
        selectedPitchClass="G"
      />,
    )
    const g = screen.getByRole('button', { name: /组成音 G/ })

    act(() => g.focus())

    expect(g).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('纯五度')
  })

  it('keeps the focused tone preview paused when the pointer leaves it', () => {
    render(
      <ChordOrbit
        intervals={['root', 'major third', 'perfect fifth']}
        onActivate={() => undefined}
        pitchClasses={['C', 'E', 'G']}
        selectedPitchClass={null}
      />,
    )
    const e = screen.getByRole('button', { name: /组成音 E/ })

    act(() => e.focus())
    fireEvent.mouseEnter(e)
    fireEvent.mouseLeave(e)

    expect(screen.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('大三度')
  })

  it('keeps the hovered tone preview paused when keyboard focus leaves it', () => {
    render(
      <ChordOrbit
        intervals={['root', 'major third', 'perfect fifth']}
        onActivate={() => undefined}
        pitchClasses={['C', 'E', 'G']}
        selectedPitchClass={null}
      />,
    )
    const e = screen.getByRole('button', { name: /组成音 E/ })

    act(() => e.focus())
    fireEvent.mouseEnter(e)
    fireEvent.blur(e)

    expect(screen.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('大三度')
  })

  it('uses concise educational language for the root', () => {
    expect(intervalEducation('root')).toEqual({
      name: '根音',
      distance: '0 个半音',
      character: '稳定、明确',
      memory: '和弦名称的起点',
    })
  })
})

describe('ChordPiano', () => {
  it('marks chord tones and the active enharmonic key without audio elements', () => {
    const { container } = render(
      <ChordPiano
        activePitchClass="Bb"
        pitchClasses={['F', 'A', 'Bb']}
      />,
    )

    expect(
      screen.getByRole('img', { name: 'F、A、Bb 的钢琴键位' }),
    ).toBeVisible()
    expect(container.querySelector('[data-pitch="A#"]')).toHaveAttribute(
      'data-active',
      'true',
    )
    expect(container.querySelectorAll('[data-chord-tone="true"]')).toHaveLength(
      3,
    )
    expect(container.querySelectorAll('audio')).toHaveLength(0)
  })
})
