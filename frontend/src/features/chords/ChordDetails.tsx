import type { ChordResult } from '../../api/types'
import { ConfidenceBadge } from '../../components/ConfidenceBadge'
import { confidenceLevel, isUsableConfidence } from '../confidence'
import { formatTime } from '../timeline/Timeline'

export interface ChordDetailsProps {
  chord: ChordResult | null
}

export function ChordDetails({ chord }: ChordDetailsProps) {
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

  return (
    <section className="chord-details" aria-labelledby="chord-details-title">
      <div className="chord-details__heading">
        <div>
          <p className="eyebrow">
            {formatTime(chord.start_seconds)}–{formatTime(chord.end_seconds)}
          </p>
          <h2 id="chord-details-title">{chord.symbol} 和弦</h2>
        </div>
        <ConfidenceBadge level={confidenceLevel(chord.confidence)} />
      </div>
      <dl className="theory-facts">
        <TheoryFact label="组成音" value={theory.pitch_classes.join(' · ')} />
        <TheoryFact label="音程" value={theory.intervals.join(' · ')} />
        <TheoryFact
          label="性质"
          value={
            theory.quality === 'major'
              ? '大三和弦'
              : theory.quality === 'minor'
                ? '小三和弦'
                : '不确定'
          }
        />
      </dl>
      <p className="theory-guide">A–G 表示音名；♯ 表示升半音；m 表示小三和弦。</p>
    </section>
  )
}

function TheoryFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
