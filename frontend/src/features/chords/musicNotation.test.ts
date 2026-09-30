import { describe, expect, it } from 'vitest'
import { fixtureResult } from '../../test/analysisFixture'
import {
  chordNotation,
  formatPitch,
  pianoRange,
  pitchNumber,
  solfege,
  teachingVoicing,
} from './musicNotation'
import { pitchClassFrequency } from './useToneAudition'

const theory = fixtureResult.chords[1].theory!
const chord = (symbol: string, pitches: string[]) => ({
  symbol,
  theory: { ...theory, pitch_classes: pitches, is_diatonic: false },
})

describe('musical notation and teaching register', () => {
  it('respells A sharp major without changing any sound', () => {
    const original = chord('A#', ['A#', 'C##', 'E#'])
    const notation = chordNotation(original)
    expect(notation).toEqual({ symbol: 'B♭', pitches: ['Bb', 'D', 'F'] })
    expect(notation.pitches.map(pitchNumber)).toEqual(
      original.theory.pitch_classes.map(pitchNumber),
    )
    expect(original.theory.pitch_classes).toEqual(['A#', 'C##', 'E#'])
  })
  it('uses musical glyphs including double accidentals', () => {
    expect(formatPitch('C## Ebb F# Bb')).toBe('C𝄪 E𝄫 F♯ B♭')
    expect(formatPitch('F♯m')).toBe('F♯m')
    expect(pitchNumber('C𝄪')).toBe(2)
    expect(solfege('Bb')).toBe('Si♭')
    expect(solfege('F#')).toBe('Fa♯')
  })
  it('preserves diatonic spelling and validates contextual candidates', () => {
    const contextual = chord('C#', ['C#', 'E#', 'G#'])
    contextual.theory.enharmonic_candidates = ['Dbm', 'D', 'Db']
    expect(chordNotation(contextual)).toEqual({
      symbol: 'D♭',
      pitches: ['Db', 'F', 'Ab'],
    })
    const inKey = {
      ...contextual,
      theory: {
        ...contextual.theory,
        is_diatonic: true,
        enharmonic_candidates: [],
      },
    }
    expect(chordNotation(inKey).symbol).toBe('C♯')
    expect(chordNotation(chord('F#m', ['F#', 'A', 'C#']))).toEqual({
      symbol: 'F♯m',
      pitches: ['F#', 'A', 'C#'],
    })
  })
  it('does not invent tones for missing theory or silently fix inconsistent evidence', () => {
    expect(chordNotation({ symbol: 'unknown', theory: null })).toEqual({
      symbol: 'unknown',
      pitches: [],
    })
    expect(chordNotation(chord('A#', ['A#', 'C#', 'E#']))).toEqual({
      symbol: 'A♯',
      pitches: ['A#', 'C#', 'E#'],
    })
  })
  it('places thirds and fifths above the root across octave boundaries', () => {
    expect(
      teachingVoicing(['G', 'B', 'D']).map((t) => [t.pitch, t.octave, t.midi]),
    ).toEqual([
      ['G', 4, 67],
      ['B', 4, 71],
      ['D', 5, 74],
    ])
    expect(teachingVoicing(['Bb', 'D', 'F']).map((t) => t.midi)).toEqual([
      70, 74, 77,
    ])
    expect(teachingVoicing(['B#', 'D##', 'F##']).map((t) => t.midi)).toEqual([
      72, 76, 79,
    ])
    expect(pitchClassFrequency('D', 5)).toBeCloseTo(587.3295, 3)
    expect(pitchClassFrequency('B♭', 4)).toBeCloseTo(466.1638, 3)
  })
  it('fits all voiced tones with white end keys and independently expands adjacent octaves', () => {
    const tones = teachingVoicing(['Bb', 'D', 'F'])
    const base = pianoRange(tones)
    expect(base.keys[0].black).toBe(false)
    expect(base.keys.at(-1)?.black).toBe(false)
    for (const tone of tones)
      expect(base.keys.some((k) => k.midi === tone.midi)).toBe(true)
    expect(pianoRange(tones, true).whiteCount).toBe(base.whiteCount + 7)
    expect(pianoRange(tones, false, true).whiteCount).toBe(base.whiteCount + 7)
    expect(pianoRange(tones, true, true).whiteCount).toBe(base.whiteCount + 14)
  })
})
