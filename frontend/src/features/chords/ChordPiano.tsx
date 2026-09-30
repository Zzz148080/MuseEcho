import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { toneVisualStyle } from './chordPalette'
import {
  formatPitch,
  pianoRange,
  solfege,
  teachingVoicing,
} from './musicNotation'
export { canonicalPitchClass } from './musicNotation'

export interface ChordPianoProps {
  pitchClasses: string[]
  activePitchClass: string | null
  activeMidi?: number | null
  onActivate?: (pitch: string, octave: number, midi: number) => void
}

export function ChordPiano({
  pitchClasses,
  activePitchClass,
  activeMidi,
  onActivate,
}: ChordPianoProps) {
  const [labels, setLabels] = useState('pitch')
  const [lower, setLower] = useState(false)
  const [upper, setUpper] = useState(false)
  const viewport = useRef<HTMLDivElement>(null)
  const tones = teachingVoicing(pitchClasses)
  const selectedMidi =
    activeMidi === undefined
      ? tones.find((tone) => tone.pitch === activePitchClass)?.midi
      : activeMidi
  const { keys, whiteCount } = pianoRange(tones, lower, upper)
  useEffect(() => {
    const root = viewport.current
    const key = root?.querySelector<HTMLElement>(
      selectedMidi != null
        ? `[data-midi="${selectedMidi}"]`
        : '[data-chord-tone="true"]',
    )
    if (!root || !key) return
    const left = key.offsetLeft
    if (
      left < root.scrollLeft ||
      left + key.offsetWidth > root.scrollLeft + root.clientWidth
    ) {
      root.scrollLeft = Math.max(
        0,
        left - root.clientWidth / 2 + key.offsetWidth / 2,
      )
    }
  }, [selectedMidi, lower, upper])
  return (
    <section className="piano-lab" aria-label="和弦钢琴示意">
      <div className="piano-toolbar">
        <label>
          琴键标注
          <select
            aria-label="琴键标注"
            value={labels}
            onChange={(event) => setLabels(event.target.value)}
          >
            <option value="pitch">音名</option>
            <option value="solfege">唱名（固定调）</option>
            <option value="none">隐藏</option>
          </select>
        </label>
        <div className="piano-range-controls" aria-label="显示相邻音区">
          <button
            type="button"
            aria-pressed={lower}
            onClick={() => setLower(!lower)}
          >
            低音区
          </button>
          <button
            type="button"
            aria-pressed={upper}
            onClick={() => setUpper(!upper)}
          >
            高音区
          </button>
        </div>
      </div>
      <p className="piano-register">
        {tones.map((t) => `${formatPitch(t.pitch)}${t.octave}`).join(' · ')}
        <span>根音起的原位示意 · 非原曲实际音区</span>
      </p>
      <div
        className="piano-viewport"
        ref={viewport}
        tabIndex={0}
        role="region"
        aria-label="钢琴音区，可横向滚动"
      >
        <div
          className="chord-piano"
          role="group"
          aria-label={`${pitchClasses.map(formatPitch).join('、')} 的钢琴键位`}
          style={{ '--white-count': whiteCount } as CSSProperties}
        >
          {keys.map((key) => {
            const tone = tones.find((t) => t.midi === key.midi)
            const preferFlats = pitchClasses.some((pitch) => /b|♭/.test(pitch))
            const flatNames: Record<string, string> = {
              'C#': 'Db',
              'D#': 'Eb',
              'F#': 'Gb',
              'G#': 'Ab',
              'A#': 'Bb',
            }
            const pitch =
              tone?.pitch ??
              (preferFlats ? (flatNames[key.pitch] ?? key.pitch) : key.pitch)
            const octave = tone?.octave ?? key.octave
            const text =
              labels === 'solfege' ? solfege(pitch) : formatPitch(pitch)
            const shared = {
              className: `chord-piano__key chord-piano__key--${key.black ? 'black' : 'white'}`,
              'data-active': String(selectedMidi === key.midi),
              'data-chord-tone': String(Boolean(tone)),
              'data-pitch': key.pitch,
              'data-midi': key.midi,
              style: {
                left: `${(key.position / whiteCount) * 100}%`,
                width: `${((key.black ? 0.62 : 1) / whiteCount) * 100}%`,
                ...(tone ? toneVisualStyle(pitch) : {}),
              },
            }
            const label =
              labels !== 'none' ? (
                <span className="piano-key-label">
                  {text}
                  <small>{octave}</small>
                </span>
              ) : null
            const marker =
              tone ? (
                <span className="piano-chord-marker" aria-hidden="true" />
              ) : null
            return onActivate ? (
              <button
                {...shared}
                type="button"
                key={key.midi}
                aria-label={`试听 ${formatPitch(pitch)}${octave}`}
                aria-pressed={selectedMidi === key.midi}
                aria-description={tone ? '和弦组成音' : undefined}
                onClick={() => onActivate(pitch, octave, key.midi)}
              >
                {marker}
                {label}
              </button>
            ) : (
              <span {...shared} aria-hidden="true" key={key.midi}>
                {marker}
                {label}
              </span>
            )
          })}
        </div>
      </div>
      <p className="piano-guide">
        所有琴键均可点击试听；彩色标注和顶部菱形表示组成音。左右滑动查看相邻琴键。
        {labels === 'solfege'
          ? '固定调：C 唱 Do，升降号保留；不是首调唱名。'
          : '音名后的数字表示八度，C4 为中央 C。'}
      </p>
    </section>
  )
}
