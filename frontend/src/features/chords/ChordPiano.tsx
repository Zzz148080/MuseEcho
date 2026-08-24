export interface ChordPianoProps {
  pitchClasses: string[]
  activePitchClass: string | null
}

const PITCH_INDEX: Readonly<Record<string, number>> = {
  C: 0,
  D: 2,
  E: 4,
  F: 5,
  G: 7,
  A: 9,
  B: 11,
}

const PIANO_KEYS = [
  { pitch: 'C', kind: 'white', left: 0 },
  { pitch: 'C#', kind: 'black', left: 10.3 },
  { pitch: 'D', kind: 'white', left: 14.285 },
  { pitch: 'D#', kind: 'black', left: 24.6 },
  { pitch: 'E', kind: 'white', left: 28.57 },
  { pitch: 'F', kind: 'white', left: 42.855 },
  { pitch: 'F#', kind: 'black', left: 53.2 },
  { pitch: 'G', kind: 'white', left: 57.14 },
  { pitch: 'G#', kind: 'black', left: 67.5 },
  { pitch: 'A', kind: 'white', left: 71.425 },
  { pitch: 'A#', kind: 'black', left: 81.8 },
  { pitch: 'B', kind: 'white', left: 85.71 },
] as const

export function canonicalPitchClass(pitch: string): string | null {
  const match = /^([A-G])([#b]{0,2})$/.exec(pitch)
  if (!match) return null
  const accidental = [...match[2]].reduce(
    (total, mark) => total + (mark === '#' ? 1 : -1),
    0,
  )
  const index = (PITCH_INDEX[match[1]] + accidental + 24) % 12
  return PIANO_KEYS.find((key) => PITCH_INDEX[key.pitch[0]] +
    (key.pitch.includes('#') ? 1 : 0) === index)?.pitch ?? null
}

export function ChordPiano({
  pitchClasses,
  activePitchClass,
}: ChordPianoProps) {
  const tones = new Set(
    pitchClasses
      .map(canonicalPitchClass)
      .filter((pitch): pitch is string => pitch !== null),
  )
  const active = canonicalPitchClass(activePitchClass ?? '')

  return (
    <div
      aria-label={`${pitchClasses.join('、')} 的钢琴键位`}
      className="chord-piano"
      role="img"
    >
      {PIANO_KEYS.map((key) => (
        <span
          aria-hidden="true"
          className={`chord-piano__key chord-piano__key--${key.kind}`}
          data-active={String(active === key.pitch)}
          data-chord-tone={String(tones.has(key.pitch))}
          data-pitch={key.pitch}
          key={key.pitch}
          style={{ left: `${key.left}%` }}
        />
      ))}
    </div>
  )
}
