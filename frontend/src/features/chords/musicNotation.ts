import type { ChordResult } from '../../api/types'

const LETTERS = 'CDEFGAB'
const NATURAL = [0, 2, 4, 5, 7, 9, 11]
export const CHROMATIC = [
  'C',
  'C#',
  'D',
  'D#',
  'E',
  'F',
  'F#',
  'G',
  'G#',
  'A',
  'A#',
  'B',
]
const MAJOR_ROOTS = [
  'C',
  'Db',
  'D',
  'Eb',
  'E',
  'F',
  'F#',
  'G',
  'Ab',
  'A',
  'Bb',
  'B',
]
const MINOR_ROOTS = [
  'C',
  'C#',
  'D',
  'D#',
  'E',
  'F',
  'F#',
  'G',
  'G#',
  'A',
  'Bb',
  'B',
]

export function asciiAccidentals(value: string): string {
  return value
    .replaceAll('𝄪', '##')
    .replaceAll('𝄫', 'bb')
    .replaceAll('♯', '#')
    .replaceAll('♭', 'b')
}

export function formatPitch(value: string): string {
  return asciiAccidentals(value)
    .replaceAll('##', '𝄪')
    .replaceAll('bb', '𝄫')
    .replaceAll('#', '♯')
    .replaceAll('b', '♭')
}

export function noteValue(value: string): number | null {
  const match = /^([A-G])([#b]{0,2})$/.exec(asciiAccidentals(value))
  if (!match) return null
  return (
    NATURAL[LETTERS.indexOf(match[1])] +
    [...match[2]].reduce((sum, sign) => sum + (sign === '#' ? 1 : -1), 0)
  )
}

export function pitchNumber(value: string): number | null {
  const number = noteValue(value)
  return number === null ? null : (number + 24) % 12
}

export function canonicalPitchClass(value: string): string | null {
  const number = pitchNumber(value)
  return number === null ? null : CHROMATIC[number]
}

function triad(symbol: string) {
  const match = /^([A-G][#b]{0,2})(m?)$/.exec(asciiAccidentals(symbol))
  if (!match) return null
  const root = pitchNumber(match[1])!
  const letter = LETTERS.indexOf(match[1][0])
  const offsets = [0, match[2] ? 3 : 4, 7]
  const pitches = offsets.map((offset, index) => {
    const nameIndex = (letter + index * 2) % 7
    let accidental = (root + offset - NATURAL[nameIndex] + 12) % 12
    if (accidental > 6) accidental -= 12
    return (
      LETTERS[nameIndex] +
      (accidental < 0 ? 'b'.repeat(-accidental) : '#'.repeat(accidental))
    )
  })
  return { root, minor: match[2] === 'm', pitches }
}

/** Respelling changes notation only, never pitch classes, quality or persisted evidence. */
export function chordNotation(chord: Pick<ChordResult, 'symbol' | 'theory'>) {
  const source = triad(chord.symbol)
  if (!source)
    return {
      symbol: formatPitch(chord.symbol),
      pitches: chord.theory?.pitch_classes ?? [],
    }
  const preferred =
    (source.minor ? MINOR_ROOTS : MAJOR_ROOTS)[source.root] +
    (source.minor ? 'm' : '')
  const contextual = chord.theory?.enharmonic_candidates.find((candidate) => {
    const parsed = triad(candidate)
    return parsed?.root === source.root && parsed?.minor === source.minor
  })
  const sourceInKey =
    chord.theory?.is_diatonic &&
    !chord.theory.limitations.includes('enharmonic-key-spelling')
  const symbol =
    contextual ??
    (sourceInKey && source.pitches.every((p) => !/##|bb/.test(p))
      ? asciiAccidentals(chord.symbol)
      : preferred)
  const target = triad(symbol)!
  const actual = chord.theory?.pitch_classes
  const consistent =
    actual?.length === 3 &&
    actual.every(
      (pitch, i) => pitchNumber(pitch) === pitchNumber(source.pitches[i]),
    )
  return {
    symbol: formatPitch(actual?.length && !consistent ? chord.symbol : symbol),
    pitches: consistent ? target.pitches : (actual ?? []),
  }
}

export interface VoicedTone {
  pitch: string
  octave: number
  midi: number
}

/** Root-position teaching voicing. The analyser does not estimate octaves. */
export function teachingVoicing(pitches: string[]): VoicedTone[] {
  let previous = -1
  return pitches.flatMap((pitch) => {
    const value = noteValue(pitch)
    if (value === null) return []
    let octave = 4
    let midi = 12 * (octave + 1) + value
    while (midi <= previous) {
      octave += 1
      midi += 12
    }
    previous = midi
    return [{ pitch, octave, midi }]
  })
}

export function solfege(pitch: string): string {
  const normalized = asciiAccidentals(pitch)
  return (
    ['Do', 'Re', 'Mi', 'Fa', 'Sol', 'La', 'Si'][
      LETTERS.indexOf(normalized[0])
    ] + formatPitch(normalized.slice(1))
  )
}

export function pianoRange(tones: VoicedTone[], lower = false, upper = false) {
  const isWhite = (midi: number) => !CHROMATIC[(midi + 120) % 12].includes('#')
  const walk = (start: number, direction: number, count: number) => {
    let midi = start
    while (count > 0 && midi > 21 && midi < 108) {
      midi += direction
      if (isWhite(midi)) count -= 1
    }
    return midi
  }
  const start = walk(
    Math.min(...tones.map((t) => t.midi), tones.length ? 108 : 60),
    -1,
    lower ? 9 : 2,
  )
  const end = walk(
    Math.max(...tones.map((t) => t.midi), tones.length ? 21 : 67),
    1,
    upper ? 9 : 2,
  )
  let white = 0
  const keys = Array.from({ length: end - start + 1 }, (_, index) => {
    const midi = start + index
    const black = !isWhite(midi)
    const position = black ? white - 0.31 : white++
    return {
      midi,
      black,
      position,
      pitch: CHROMATIC[midi % 12],
      octave: Math.floor(midi / 12) - 1,
    }
  })
  return { keys, whiteCount: white }
}
