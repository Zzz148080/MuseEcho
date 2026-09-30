import { useState } from 'react'
import type { ChordResult } from '../../api/types'
import { ConfidenceBadge } from '../../components/ConfidenceBadge'
import { confidenceLevel, isUsableConfidence } from '../confidence'
import { formatTime } from '../timeline/Timeline'
import { ChordOrbit, intervalEducation } from './ChordOrbit'
import { ChordPiano } from './ChordPiano'
import {
  chordVisualStyle,
  chordVisualTheme,
  toneVisualStyle,
} from './chordPalette'
import { chordNotation, formatPitch, teachingVoicing } from './musicNotation'
import { useToneAudition } from './useToneAudition'

export interface ChordDetailsProps {
  chord: ChordResult | null
}

interface SelectedTone {
  pitchClass: string
  interval: string
}

const QUALITY_COPY = {
  major: {
    name: '大三和弦',
    character: '明亮、稳定，常带有清晰的展开感。',
    context: '常用于建立明朗感、稳定感或清晰收束。',
  },
  minor: {
    name: '小三和弦',
    character: '柔和、内敛，常带有含蓄的张力。',
    context: '常用于营造内省、克制或细腻的段落。',
  },
} as const

export function ChordDetails({ chord }: ChordDetailsProps) {
  const [selectedTone, setSelectedTone] = useState<SelectedTone | null>(null)
  const [activeMidi, setActiveMidi] = useState<number | null>(null)
  const tone = useToneAudition()

  if (!chord) {
    return (
      <section className="chord-details" aria-labelledby="chord-details-title">
        <h2 id="chord-details-title">和弦详情</h2>
        <p>点击地图中的和声线索，查看组成音与音程。</p>
      </section>
    )
  }
  const theory =
    chord.symbol === 'unknown' || !isUsableConfidence(chord.confidence)
      ? null
      : chord.theory
  if (!theory) {
    return (
      <section className="chord-details" aria-labelledby="chord-details-title">
        <p className="eyebrow">
          {formatTime(chord.start_seconds)}–{formatTime(chord.end_seconds)}
        </p>
        <h2 id="chord-details-title">和弦详情</h2>
        <p className="unknown-copy">暂无可用的和声细节。</p>
      </section>
    )
  }

  const notation = chordNotation(chord)
  const voicing = teachingVoicing(notation.pitches)
  const quality = QUALITY_COPY[theory.quality]
  const chordTheme = chordVisualTheme(chord.symbol)
  const activateTone = (pitchClass: string, interval: string) => {
    const voiced = voicing.find((note) => note.pitch === pitchClass)
    setSelectedTone({ pitchClass, interval })
    setActiveMidi(voiced?.midi ?? null)
    tone.audition(pitchClass, voiced?.octave ?? 4)
  }

  return (
    <section
      aria-labelledby="chord-details-title"
      className="chord-details"
      data-chord-family={chordTheme.family}
      style={chordVisualStyle(chord.symbol)}
    >
      <div className="chord-details__heading">
        <div>
          <p className="eyebrow">
            {formatTime(chord.start_seconds)}–{formatTime(chord.end_seconds)}
          </p>
          <h2 id="chord-details-title">{notation.symbol} 和弦</h2>
        </div>
        <ConfidenceBadge level={confidenceLevel(chord.confidence)} />
      </div>

      <div className="chord-lab">
        <div className="chord-lab__visual">
          <div className="galaxy-caption">
            <span>和弦星系</span>
            <span>
              {notation.pitches.map(formatPitch).join(' · ')}
              <small>选择音符，听见它的位置</small>
            </span>
          </div>
          <ChordOrbit
            intervals={theory.intervals}
            onActivate={activateTone}
            pitchClasses={notation.pitches}
            selectedPitchClass={selectedTone?.pitchClass ?? null}
          />
          <ChordPiano
            onActivate={(pitch, octave, midi) => {
              const index = voicing.findIndex((note) => note.midi === midi)
              setActiveMidi(midi)
              setSelectedTone(
                index < 0
                  ? null
                  : {
                      pitchClass: voicing[index].pitch,
                      interval: theory.intervals[index] ?? '',
                    },
              )
              tone.audition(pitch, octave)
            }}
            activeMidi={activeMidi}
            activePitchClass={selectedTone?.pitchClass ?? null}
            pitchClasses={notation.pitches}
          />
          <p className="theory-guide">
            A–G 表示音名；♯ 表示升半音；♭ 表示降半音。
          </p>
          {tone.unavailable ? (
            <p className="tone-audition-status" role="status">
              此设备暂不支持试听
            </p>
          ) : null}
        </div>

        <section
          aria-live="polite"
          className="tone-education"
          style={
            selectedTone ? toneVisualStyle(selectedTone.pitchClass) : undefined
          }
        >
          {selectedTone ? (
            <ToneEducation
              key={selectedTone.pitchClass}
              interval={selectedTone.interval}
              pitchClass={selectedTone.pitchClass}
            />
          ) : (
            <p className="tone-education__empty">选择一个组成音</p>
          )}
        </section>

        <section
          aria-labelledby="general-theory-title"
          className="general-theory"
        >
          <div className="general-theory__heading">
            <p className="eyebrow">不结合歌曲上下文</p>
            <h3 id="general-theory-title">通用乐理</h3>
          </div>
          <dl className="theory-facts theory-facts--concise">
            <TheoryFact label="构成">
              <span>{notation.pitches.map(formatPitch).join(' · ')}</span>
              <small>{quality.name}</small>
            </TheoryFact>
            <TheoryFact label="听感">{quality.character}</TheoryFact>
            <TheoryFact label="情境">{quality.context}</TheoryFact>
          </dl>
        </section>
      </div>
    </section>
  )
}

function ToneEducation({
  pitchClass,
  interval,
}: {
  pitchClass: string
  interval: string
}) {
  const education = intervalEducation(interval)
  return (
    <>
      <h3>
        {formatPitch(pitchClass)} · {education.name}
      </h3>
      <dl>
        <TheoryFact label="音程距离">{education.distance}</TheoryFact>
        <TheoryFact label="听感提示">{education.character}</TheoryFact>
        <TheoryFact label="记忆方法">{education.memory}</TheoryFact>
      </dl>
    </>
  )
}

function TheoryFact({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}
