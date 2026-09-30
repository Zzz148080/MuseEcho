import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ChordPiano } from './ChordPiano'

it('switches names, solfege and hidden labels without changing the voiced keys', async () => {
  const user = userEvent.setup()
  const onActivate = vi.fn()
  const { container } = render(
    <ChordPiano
      pitchClasses={['Bb', 'D', 'F']}
      activePitchClass="D"
      onActivate={onActivate}
    />,
  )
  const third = screen.getByRole('button', { name: '试听 D5' })
  expect(third).toHaveAttribute('data-midi', '74')
  expect(third).toHaveAttribute('aria-pressed', 'true')
  await user.click(third)
  expect(onActivate).toHaveBeenCalledWith('D', 5, 74)
  await user.selectOptions(screen.getByLabelText('琴键标注'), 'solfege')
  expect(third).toHaveTextContent('Re5')
  expect(screen.getByRole('button', { name: '试听 B♭4' })).toHaveTextContent(
    'Si♭4',
  )
  await user.selectOptions(screen.getByLabelText('琴键标注'), 'none')
  expect(container.querySelectorAll('.piano-key-label')).toHaveLength(0)
  expect(third).toHaveAccessibleName('试听 D5')
  await user.click(screen.getByRole('button', { name: '低音区' }))
  await user.click(screen.getByRole('button', { name: '高音区' }))
  expect(container.querySelectorAll('[data-chord-tone="true"]')).toHaveLength(3)
  expect(container.querySelectorAll('[data-pitch="D"]')).toHaveLength(3)
  expect(container.querySelector('[data-active="true"]')).toHaveAttribute(
    'data-midi',
    '74',
  )
})

it('makes every key playable at its own octave without coloring non-chord keys', async () => {
  const user = userEvent.setup()
  const onActivate = vi.fn()
  const { container } = render(
    <ChordPiano
      pitchClasses={['Bb', 'D', 'F']}
      activePitchClass={null}
      activeMidi={72}
      onActivate={onActivate}
    />,
  )
  expect(container.querySelectorAll('button.chord-piano__key')).toHaveLength(
    container.querySelectorAll('.chord-piano__key').length,
  )
  await user.click(screen.getByRole('button', { name: '试听 C5' }))
  expect(onActivate).toHaveBeenLastCalledWith('C', 5, 72)
  const nonChord = screen.getByRole('button', { name: '试听 D♭5' })
  await user.click(nonChord)
  expect(onActivate).toHaveBeenLastCalledWith('Db', 5, 73)
  expect(nonChord).toHaveAttribute('data-chord-tone', 'false')
  expect(nonChord.style.getPropertyValue('--tone-accent')).toBe('')
  await user.click(screen.getByRole('button', { name: '低音区' }))
  await user.click(screen.getByRole('button', { name: '试听 D4' }))
  expect(onActivate).toHaveBeenLastCalledWith('D', 4, 62)
  expect(screen.getByRole('button', { name: '试听 D4' })).toHaveAttribute(
    'data-chord-tone',
    'false',
  )
  await user.selectOptions(screen.getByLabelText('琴键标注'), 'none')
  expect(container.querySelectorAll('.piano-chord-marker')).toHaveLength(3)
  expect(container.querySelectorAll('[data-chord-tone="true"]')).toHaveLength(3)
})
