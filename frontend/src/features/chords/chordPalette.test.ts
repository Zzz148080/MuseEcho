import { describe, expect, it } from 'vitest'
import { chordVisualTheme } from './chordPalette'

describe('chordVisualTheme', () => {
  it('keeps enharmonic roots together and separates different roots', () => {
    const c = chordVisualTheme('C')
    const cMinor = chordVisualTheme('Cm')
    const g = chordVisualTheme('G')
    const aSharp = chordVisualTheme('A#')
    const bFlat = chordVisualTheme('Bb')

    expect(c.family).toBe(cMinor.family)
    expect(c.accent).not.toBe(g.accent)
    expect(aSharp).toEqual(bFlat)
  })

  it('uses one restrained fallback for unknown symbols', () => {
    expect(chordVisualTheme('unknown')).toEqual(chordVisualTheme(''))
  })
})
