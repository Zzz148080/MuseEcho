import { formatPitch } from './musicNotation'
import { useState, type CSSProperties } from 'react'
import { toneVisualStyle } from './chordPalette'

export interface ChordOrbitProps {
  pitchClasses: string[]
  intervals: string[]
  selectedPitchClass: string | null
  onActivate: (pitchClass: string, interval: string) => void
}

export interface IntervalEducation {
  name: string
  distance: string
  character: string
  memory: string
}

const INTERVAL_COPY: Readonly<Record<string, IntervalEducation>> = {
  root: {
    name: '根音',
    distance: '0 个半音',
    character: '稳定、明确',
    memory: '和弦名称的起点',
  },
  'major third': {
    name: '大三度',
    distance: '4 个半音',
    character: '明亮、开阔',
    memory: '从根音向上数四个半音',
  },
  'minor third': {
    name: '小三度',
    distance: '3 个半音',
    character: '柔和、内敛',
    memory: '从根音向上数三个半音',
  },
  'perfect fifth': {
    name: '纯五度',
    distance: '7 个半音',
    character: '稳定、有支撑',
    memory: '从根音向上数七个半音',
  },
}

export function intervalEducation(interval: string): IntervalEducation {
  return (
    INTERVAL_COPY[interval] ?? {
      name: interval || '组成音',
      distance: '以当前记录为准',
      character: '可与其他组成音对照聆听',
      memory: '记住它与根音的相对位置',
    }
  )
}

export function ChordOrbit({
  pitchClasses,
  intervals,
  selectedPitchClass,
  onActivate,
}: ChordOrbitProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)
  const previewIndex = hoveredIndex ?? focusedIndex
  const preview =
    previewIndex === null
      ? null
      : {
          pitch: pitchClasses[previewIndex],
          ...intervalEducation(intervals[previewIndex] ?? ''),
        }

  return (
    <div
      className="chord-orbit"
      data-paused={String(previewIndex !== null)}
      data-testid="chord-orbit"
    >
      <div className="chord-orbit__stage">
        <div
          aria-hidden="true"
          className="chord-orbit__rings"
          style={{ pointerEvents: 'none' }}
        >
          {pitchClasses.map((pitch, index) => (
            <span
              className="chord-orbit__ring"
              data-orbit-index={index}
              key={`${pitch}-ring`}
              style={
                {
                  '--orbit-index': index,
                  ...toneVisualStyle(pitch),
                } as CSSProperties
              }
            />
          ))}
        </div>
        <span aria-hidden="true" className="chord-orbit__centre">
          组成音
        </span>
        {pitchClasses.map((pitch, index) => {
          const education = intervalEducation(intervals[index] ?? '')
          return (
            <span
              className="chord-orbit__carrier"
              data-orbit-index={index}
              key={`${pitch}-${index}`}
              style={
                {
                  '--orbit-index': index,
                  ...toneVisualStyle(pitch),
                } as CSSProperties
              }
            >
              <span className="chord-orbit__note-anchor">
                <span className="chord-orbit__note-upright">
                  <button
                    aria-describedby={
                      previewIndex === index ? 'chord-tone-preview' : undefined
                    }
                    aria-label={`组成音 ${formatPitch(pitch)}，${education.name}`}
                    aria-pressed={selectedPitchClass === pitch}
                    className="chord-orbit__note"
                    data-pitch={formatPitch(pitch)}
                    onBlur={() => setFocusedIndex(null)}
                    onClick={() => onActivate(pitch, intervals[index] ?? '')}
                    onFocus={() => setFocusedIndex(index)}
                    onMouseEnter={() => setHoveredIndex(index)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    type="button"
                  >
                    {formatPitch(pitch)}
                  </button>
                </span>
              </span>
            </span>
          )
        })}
      </div>
      <div className="chord-orbit__tooltip-slot">
        {preview ? (
          <div
            className="chord-orbit__tooltip"
            id="chord-tone-preview"
            role="tooltip"
            style={toneVisualStyle(preview.pitch)}
          >
            <strong>
              {formatPitch(preview.pitch)} · {preview.name}
            </strong>
            <span>
              {preview.distance} · {preview.character}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
